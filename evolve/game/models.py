import random
import collections

from django.db import models
from django.contrib.auth.models import User

from evolve.rules.models import (
    Score,
    City, CitySpecial, Variant, Age, Building, BuildOption, Effect, Science,
    PERSONALITY, TRADEABLE
)
from evolve.rules import constants, economy


# Game models where state is kept

class Game(models.Model):
    """A single match of the game, including all global game status"""
    # game settings
    allowed_variants = models.ManyToManyField(Variant)

    # game state
    age = models.ForeignKey(Age, default=Age.first)
    turn = models.PositiveIntegerField(default=1)
    discards = models.ManyToManyField(BuildOption, blank=True, null=True)
    
    # status for the join/play/finish cycle
    started = models.BooleanField(default=False)
    finished = models.BooleanField(default=False)

    special_use_discards_turn = models.BooleanField(default=False) # set when a player is picking from the discard pile

    def is_joinable(self, user=None):
        """True if the game has still room for more players and user, is specified, isn't already playing"""
        available_cities = City.objects.exclude(player__game=self)
        user_not_playing = user is None or not self.get_player(user)
        return not self.started and bool(available_cities) and bool(user_not_playing)

    def join(self, user):
        """Make the given user join to this game"""
        assert self.is_joinable()
        # Pick a city
        available_cities = list(City.objects.exclude(player__game=self))
        variants = list(self.allowed_variants.all())
        assert variants # should be at least one, by modeling
        if not available_cities:
            raise City.DoesNotExist
        # Create player
        player = Player(
            user=user,
            game=self,
            variant=random.choice(variants),
            city=random.choice(available_cities),
        )
        player.save()
        # TODO: if all cities assigned, game should auto-start?
        
    def is_startable(self):
        """True if game can be started"""
        return not self.started and self.player_set.count() >= constants.MINIMUM_PLAYERS

    def start(self):
        """Put the game in its initial state, and ready to play"""
        assert self.is_startable()
        assert not self.finished
        assert self.age == Age.first()
        assert self.discards.count() == 0
        assert self.turn == 1
        # Start!
        self.started = True
        self.save()
        # Shuffle build options for this age
        self.shuffle()
    start.alters_data = True

    def shuffle(self):
        """Assign to each player the build options"""
        assert self.started
        assert not self.finished

        n = self.player_set.count()
        required_options = n * constants.INITIAL_OPTIONS

        options = list(BuildOption.objects.filter(
            age=self.age,
            players_needed__lte=n
        ).exclude(
            building__kind__name=PERSONALITY
        ).order_by('?'))
        personalities = list(BuildOption.objects.filter(
            age=self.age,
            players_needed__lte=n,
            building__kind__name=PERSONALITY
        ).order_by('?'))

        # Check that there are enough options for everyone
        if len(options)+len(personalities) < required_options:
            raise BuildOption.DoesNotExist

        # Figure out how many personalities to use
        required_personalities = required_options - len(options)
        recommended_personalities = 2+n
        #   actual = Clip recommended in range [required..available]
        actual_personalities = min(max(recommended_personalities, required_personalities), len(personalities))

        # Remove unused personalities
        del personalities[actual_personalities:]
        # Remove unused options, replace by personalities
        options[required_options-len(personalities):] = personalities
        # Reshuffle, to mix personalities and the rest of the options
        random.shuffle(options)
        
        # Now the set of options is built. Assign
        assert len(options) == required_options
        for p in self.player_set.all():
            assert not p.current_options.all() # No options when shuffling
            p.current_options.add(*options[:constants.INITIAL_OPTIONS])
            del options[:constants.INITIAL_OPTIONS]
    shuffle.alters_data = True

    def get_player(self, user):
        """Return player for user, or None if user not part of this game"""
        try:
            return self.player_set.get(user=user)
        except Player.DoesNotExist:
            return None

    def end_of_age(self):
        # discard cards for all players
        for p in self.player_set.all():
            self.discards.add(*p.current_options.all())
            p.current_options.clear()
        # Battles
        for p in self.player_set.all():
            for neighbor, d in zip((p.left_player(), p.right_player()),'lr'):
                local = p.military()
                foreign = neighbor.military()
                if local != foreign: # There was a winner
                    result = 'v' if local > foreign else 'd'
                    BattleResult.objects.create(owner=p, direction=d, age=self.age, result=result)
        next_age = self.age.next()
        if next_age is None:
            self.finished = True
            self.save()
        else:
            # Increase age
            self.age = next_age
            self.turn = 1
            # new cards
            self.save()
            self.shuffle()
    end_of_age.alters_data = True

    def end_of_turn(self):
        # Apply all player actions, in two stages
        for p in self.player_set.all():
            p.pre_apply_action()
        for p in self.player_set.all():
            p.apply_action()
        # Rotate available options
        opts = [list(p.current_options.all()) for p in self.player_set.all()]
        if self.age.direction=='l':
            opts = opts[1:]+opts[:1]
        else:
            assert self.age.direction=='r'
            opts = opts[-1:]+opts[:-1]
        for p, os in zip(self.player_set.all(), opts):
            p.current_options.clear()
            p.current_options.add(*os)
        # increase turn counter
        self.turn += 1
        if self.turn > constants.TURN_COUNT:
            self.end_of_age()
        else:
            self.save()
        # Reset players so they can play again
        for p in self.player_set.all():
            p.reset_action()
    end_of_turn.alters_data = True

    def missing_players(self):
        """This is the list of players who haven't played yet"""
        return self.player_set.filter(action='')

    def waiting_players(self):
        """This is the list of players who have already played"""
        return self.player_set.exclude(action='')

    def turn_check(self):
        """Checks if we need to do end of turn"""
        if not self.missing_players():
            self.end_of_turn()
    turn_check.alters_data = True

    def discard(self, option):
        """Discard one option"""
        self.discards.add(option)

    @models.permalink
    def get_absolute_url(self):
        return ('game-detail', [], {'pk': self.id})


class Player(models.Model):
    """Single player information for given game"""

    BUILD_ACTION= 'build'
    FREE_ACTION = 'free'
    SELL_ACTION = 'sell'
    SPECIAL_ACTION = 'spec'
    ACTIONS = (
        (BUILD_ACTION, 'Build'),
        (FREE_ACTION, 'Build(free, use special)'),
        (SELL_ACTION, 'Sell'),
        (SPECIAL_ACTION, 'Build special'),
    )
    
    user = models.ForeignKey(User)
    game = models.ForeignKey(Game)

    city = models.ForeignKey(City)
    variant = models.ForeignKey(Variant)

    # General information
    money = models.PositiveIntegerField(default=constants.INITIAL_MONEY)
    # All specials for the city/variant with order strictly lower than
    # specials_built are considered built.
    specials_built = models.PositiveIntegerField(default=0)
    # battle_result_set = results of battles
    buildings = models.ManyToManyField(Building, blank=True, null=True)
    # Ages where the special_free_bulding ability has been used already
    special_free_building_ages_used = models.ManyToManyField(Age, blank=True, null=True)

    # Private information, player decisions
    current_options = models.ManyToManyField(BuildOption, blank=True, null=True)
    option_picked = models.ForeignKey(BuildOption, blank=True, null=True, related_name='picker_set')
    action = models.CharField(max_length=5, choices=ACTIONS, blank=True)
    trade_left = models.PositiveIntegerField(default=0) # Money used in trade with left player
    trade_right = models.PositiveIntegerField(default=0) # Money used in trade with right player

    def building_list(self):
        """Building list, sorted by kind. For template use"""
        result = [dict(
            kind='bas' if self.city.resource.is_basic else 'cpx', # FIXME: hardocded constant
            label='City',
            building=None,
            effect=self.city.resource.name
        )]
        for b in self.buildings.all():
            result.append(dict(
                kind=b.kind.pk,
                label=b.name,
                building=b,
                effect=b.effect
            ))
        ORDERING = ['bas', 'cpx', 'eco', 'civ', 'sci', 'mil', 'per']
        result.sort(key=lambda b:ORDERING.index(b['kind']))
        return result

    def active_effects(self):
        """The set of effects which apply to this player"""
        # City specials
        city_effects = Effect.objects.filter(cityspecial__city=self.city, cityspecial__variant=self.variant, cityspecial__order__lt=self.specials_built)
        # Building effects
        effects = city_effects | Effect.objects.filter(building__player=self)
        return effects

    def left_player(self):
        try:
            return self.get_previous_in_order()
        except:
            return self.game.player_set.order_by('-_order')[0]

    def right_player(self):
        try:
            return self.get_next_in_order()
        except:
            return self.game.player_set.order_by('_order')[0]
    
    def all_right_players(self):
        """
        A list of every player except self and player at the left, starting
        by the player at the right and going around to the right
        """
        p = self.right_player()
        result = []
        for _ in range(self.game.player_set.count()-2):
            result.append(p)
            p = p.right_player()
        assert p == self.left_player()
        return result
    
    def tradeable_resources(self):
        """
        List of resources that can be bought by neighbors; note that not
        every resource available is tradeable.
        
        This a [[(amount, resource)]]. Inner list are alternative resources
        """
        # Basic city resource is tradeable
        result = [[(1, self.city.resource.name)]]
        # Add in production of resources by tradeable kinds of buildings
        for b in self.buildings.filter(kind__in=TRADEABLE):
            if b.effect.production:
                result.append(b.effect.production.to_list())
        return result

    def trade_costs(self, direction):
        """
        Costs of trading with player in given direction ('l' or 'r')
        
        dict of resource_name -> money
        """
        assert direction in ('l', 'r')
        result = collections.defaultdict(lambda: constants.DEFAULT_TRADE_COST)
        for e in self.active_effects():
            if (direction=='l' and e.left_trade) or (direction=='r' and e.right_trade):
                cost = e.trade.money
                for _, resource in e.trade.to_list():
                    # Pick the better value for each resource
                    result[resource] = min(result[resource], cost)
        return result
        

    def local_production(self):
        """
        List of resources produced by every local effect (not counting trade)
        
        This a [[(amount, resource)]]. Inner list are alternative resources
        """
        # Basic city resource is local production
        result = [[(1, self.city.resource.name)]]
        # Add in production of resources by tradeable kinds of buildings
        for e in self.active_effects():
            if e.production:
                result.append(e.production.to_list())
        return result
    
    def can_play(self):
        return self.game.started and not self.game.finished and self.action == ''

    def can_build_free(self):
        """
        True if player can use the 'free building' effect. Needs to have the
        effect available, and not already used in this age.
        """
        # This only makes sense on started games
        if not self.game.started: return False
        # Check that the player has the free build ability
        if not self.active_effects().filter(free_building=True): return False
        # Check that the effect hasn't been already used
        if special_free_building_ages_used.filter(game=self.game): return False
        # Otherwise, the effect can be used
        return True

    def play(self, action, option, trade_left, trade_right):
        """
        Choose to play the given action with the given build option.
        
        Note that this is the selection of the option, the action is not applied
        until the end of turn (which is checked at the end of this method).
        
        Preconditions:
         - action is one of the Player.ACTIONS
         - option in self.current_options.all()
         - option == FREE_ACTION implies self.can_build_free()
         - option == SPECIAL_ACTION implies self.can_build_special()
         - option == BUILD_ACTION implies option.cost can be paid with given trade
        """
        assert action in (name for name,label in self.ACTIONS)
        assert option in self.current_options.all()
        assert option != self.FREE_ACTION or self.can_build_free()
        assert option != self.SPECIAL_ACTION or self.can_build_special()
        assert option != self.BUILD_ACTION or economy.can_pay(self.payment_options(option.building), trade_left, trade_right)
        
        self.action = action
        self.option_picked = option
        self.trade_left = trade_left
        self.trade_right = trade_right
        self.save()
        
        self.game.turn_check()

    def reset_action(self):
        self.action = ''
        self.option_picked = None
        self.trade_left = 0
        self.trade_right = 0
        self.save()
    reset_action.alters_data = True

    def pre_apply_action(self):
        """
        Pre-apply action played
        (actions are applied in two phases)
        """
        assert self.action
        # Buildings need to be added first, so applied effects related to
        # existing buildings count other buildings built in the same turn
        if self.action in (self.BUILD_ACTION, self.FREE_ACTION):
            if self.action==self.BUILD_ACTION:
                item = self.option_picked.building
            else:
                item = self.next_special() 
            # Check payment. This needs to be done before building, so raising
            # a commercial building does not affect its own price, and building
            # a resource does not allow to pay for itself.
            # Anyway, build options should try to avoid that happening
            payment = economy.can_pay(
                self.payment_options(item), 
                self.trade_left,
                self.trade_right
            )
            assert payment is not None
            # Pay local money. Trade is handled later
            self.money -= payment.money
            self.buildings.add(self.option_picked.building)
        
    def apply_action(self):
        """Apply action played"""
        assert self.action
        if self.action == self.SELL_ACTION:
            # Sell: discard the option
            self.game.discard(self.option_picked)
            # Get money
            self.money += constants.SELL_VALUE

            self.save()

        elif self.action == self.BUILD_ACTION:
            # Pay!
            if self.trade_left:
                self.left_player().money += self.trade_left
                self.money -= self.trade_left
                self.left_player().save()
            if self.trade_right:
                self.right_player().money += self.trade_right
                self.money -= self.trade_right
                self.right_player().save()
            # Earn money if building produces money
            self.money += self.option_picked.building.effect.money(
                self,
                self.left_player(),
                self.right_player()
            )
            self.save()
        elif self.action == self.FREE_ACTION:
            assert self.can_build_free()
            # "Pay" with one use of the ability. No actual costs, but ability is disabled for this age
            special_free_building_ages_used.add(self.game.age)
            # Earn money if building produces money
            self.money += self.option_picked.building.effect.money(
                self,
                self.left_player(),
                self.right_player()
            )
            self.save()
            # Build
        elif self.action == self.SPECIAL_ACTION:
            assert self.can_build_special()
            special = self.next_special()
            # Pay!
            if self.trade_left:
                self.left_player().money += self.trade_left
                self.money -= self.trade_left
                self.left_player().save()
            if self.trade_right:
                self.right_player().money += self.trade_right
                self.money -= self.trade_right
                self.right_player().save()
            # Earn money if building produces money
            self.money += special.effect.money(
                self,
                self.left_player(),
                self.right_player()
            )
            # "Build"
            self.specials_built = special.order + 1
            self.save()
        else:
            raise AssertionError
        # Option no longer available
        self.current_options.remove(self.option_picked)
    apply_action.alters_data = True

    def next_special(self):
        """
        Next special to build, None if all built
        """
        specials = CitySpecial.objects.filter(city=self.city, variant=self.variant, order__gte=self.specials_built).order_by('order')
        if specials:
            return specials[0]

    def can_build_special(self):
        """
        True if player can use the 'build special' action. Needs to have an
        available special, and resources to pay for it
        """
        # This only makes sense on started games
        if not self.game.started: return False
        # Check that there is a next special to build
        special = self.next_special()
        if special is None: return False
        # Check that the player can pay for the special
        return bool(self.payment_options(special))

    def count(self, kind):
        """Number of buildings of a given kind"""
        return self.buildings.filter(kind=kind).count()
    
    def specials(self):
        """Number of specials built"""
        return self.specials_built

    def defeats(self):
        """Number of defeats suffered"""
        return self.battleresult_set.filter(result='d').count() # FIXME: hardcoded constant

    def all_specials(self):
        """The complete list of specials for our city+variant"""
        return CitySpecial.objects.filter(city=self.city, variant=self.variant).order_by('order')

    def military(self):
        """Military power"""
        # Just the sum of the military powers of each effect
        return self.active_effects().aggregate(models.Sum('military'))

    def science_score(self):
        """Amount of science points"""
        ### Science score
        # Build auxiliar science class
        sciences = Science.objects.values_list('name', flat=True)
        ScienceScore = collections.namedtuple('ScienceScore', ' '.join(sciences))
        # compute list of science producing effects
        options = [e.sciences.all() for e in self.active_effects() if e.sciences.count()]
        
        combinations = oldcombinations = set([ScienceScore(*[0]*len(sciences))]) # Science score for a player with no science effects
        for o in options:
            combinations = set()
            for science in o:
                for b in oldcombinations:
                    combinations.add(b._replace(**{science.name: getattr(b, science.name)+1}))
            oldcombinations = combinations

        result = 0
        for s in combinations:
            value = min(s)*constants.SCIENCE_SCORE_PER_GROUP + sum(amount**2 for amount in s)
            result = max(result, value)
        return result
    
    def score(self):
        """Score for this player"""
        treasury_score = self.money // 3

        military_score = sum(b.score() for b in self.battleresult_set.all())

        specials_built = Effect.objects.filter(cityspecial__city=self.city, cityspecial__variant=self.variant, cityspecial__order__lt=self.specials_built)    
        special_score = sum(s.get_score(self, self.left_player(), self.right_player()) for s in specials_built)
        
        # Accumulate building effects
        result = Score.new()._replace(
            treasury=treasury_score,
            military=military_score,
            special=special_score,
            science=self.science_score()
        )
        for b in self.buildings.all():
            result = result + b.score(self, self.left_player(), self.right_player())

        return result

    def payment_options(self, item):
        """List of ways of paying for item.cost. Empty if unpayable"""
        # Can't be bought if we already have it
        if item in self.buildings.all():
            return []
        # Check if we have a dependency of this item that makes it free:
        if hasattr(item, 'free_having'):
            if item.free_having in self.buildings.all():
                # You can get it for free. No more options needed
                return [economy.PaymentOption()]
        return economy.get_payments(
            item.cost.to_dict(),
            self.money,
            self.local_production(),
            self.left_player().tradeable_resources(),
            self.trade_costs('l'),
            self.right_player().tradeable_resources(),
            self.trade_costs('r'),
        )            

    class Meta:
        unique_together = (
            ('city', 'game'), # No two players can have the same city at the same game
            ('user', 'game'), # A user can't play as two players (this can be changed, but there's a UI limitation right now)
        )
        order_with_respect_to = 'game'

    def __unicode__(self):
        return unicode(self.user)

class BattleResult(models.Model):
    """
    Result of a battle where a player fought.
    If there was no victory nor a defeat, no battle tokens are given.
    """
    owner = models.ForeignKey(Player)
    age = models.ForeignKey(Age)
    direction = models.CharField(max_length=1, choices=constants.DIRECTIONS)
    result = models.CharField(max_length=1, choices=(('v', 'Victory'),('d','Defeat')))

    def score(self):
        if self.result == 'v':
            return self.age.victory_score
        else: 
            return self.age.defeat_score
        
    class Meta:
        ordering = ('age',)
