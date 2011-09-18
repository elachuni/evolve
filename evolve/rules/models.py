# encoding: utf-8
"""
Basic "rule" models. These are loaded from fixtures and not changed
during play
"""

from django.db import models

# Basic listings. This probably will always be fixed and won't be changed
# even while balancing. Adding items to any of these models would probably
# imply a large impact on gameplay

KINDS = (
    ('mil','Military'),
    ('civ','Civilian'),
    ('bas','Basic Resource'),
    ('cpx','Complex Resource'),
    ('eco','Economic'),
    ('sci','Scientific'),
    ('per','Personality'),
)

class BuildingKind(models.Model):
    """Possible building kinds"""

    name = models.CharField(max_length=5, choices=KINDS, blank=True, null=True)

    def __unicode__(self):
        return self.name

    class Meta:
        ordering = ('name',)
    
class Resource(models.Model):
    """Each of the possible resources to collect"""
    name = models.CharField(max_length=30, unique=True)
    is_basic = models.BooleanField()

    def __unicode__(self):
        return self.name

    class Meta:
        ordering = ('is_basic', 'name',)

class Science(models.Model):
    """Each of the available sciences"""
    name = models.CharField(max_length=30, unique=True)

    def __unicode__(self):
        return self.name

    class Meta:
        ordering = ('name',)

class Variant(models.Model):
    """
    One instance of this model exists per possible variant of cities.
    Typically only one or two globally.
    """
    label = models.CharField(max_length=30, unique=True)

    def __unicode__(self):
        return self.label

    class Meta:
        ordering = ('label',)

class Age(models.Model):
    """
    Each of the phases in a game
    """
    name = models.CharField(max_length=30)
    order = models.PositiveIntegerField() # Phases are played from lower to higher
    victory_score = models.IntegerField() # Score given at this phase per military victory
    defeat_score = models.IntegerField(default=-1) # Score given at this phase per military defeat

    def __unicode__(self):
        return self.name

    class Meta:
        ordering = ('name',)

# Other listings that can be tuned to balance or add slight variantions to
# the gameplay

class Cost(models.Model):
    """Representation of the cost of something and related operations.
    
    Also used to represent other sets of resources+money
    """
    money = models.PositiveIntegerField(default=0)
    # cost_line_set =  set of resource costs [reverse]

    def __unicode__(self):
        return "$%d, %s" % (
            self.money,
            ", ".join(self.cost_line_set.all())
        )

    class Meta:
        ordering = ('money',)


class CostLine(models.Model):
    """An item inside a cost description"""
    cost = models.ForeignKey(Cost)
    amount = models.PositiveIntegerField()
    resource = models.ForeignKey(Resource)

    def __unicode__(self):
        return "%d×%s" % (self.amount, self.resource)

    class Meta:
        unique_together = (
            ('cost', 'resource'), # Normalize: resources appear only once per cost
        )
        ordering = ('resource', 'amount')

class City(models.Model):
    """A city where a player builds"""
    name = models.CharField(max_length=30)
    resource = models.ForeignKey(Resource)
    # city_special_set = set of specials

    class Meta:
        ordering = ('name',)

class Effect(models.Model):
    """
    The effect of a card or special. Note that typically only one of the
    fields will be used, but multiple can be
    """

    # Production here is a "Cost" but acts as an "income". money income is
    # instantaneous (when the effect is applied), and when more than one
    # resource is at the cot, it means that at most one of the resources is
    # produced.
    production = models.ForeignKey(Cost, blank=True, null=True, related_name='payed_effect_set')
    score = models.PositiveIntegerField(default=0) # Score given by the effect
    military = models.PositiveIntegerField(default=0) # military power of the effect

    # An effect can provide many kind of sciences. Only one of them will have
    # to be selected for scoring purposes
    sciences = models.ManyToManyField(Science, blank=True, null=True)
    
    # Trade: again a "cost" used in a special way. The money amount is the
    # cost of trading. Only one of the resources in the cost can be traded
    trade = models.ForeignKey(Cost, blank=True, null=True, related_name='trade_benefit_on_effect_set')
    left_trade = models.BooleanField()
    right_trade = models.BooleanField()
    
    # This effect produces a certain amount of money
    # per building of the kind "kind payed" built by 2 neighbours and/or player
    kind_payed = models.ForeignKey(BuildingKind, blank=True, null=True, related_name='money_benefiting_effects')
    money_per_neighbor_building = models.PositiveIntegerField(default=0)
    money_per_local_building = models.PositiveIntegerField(default=0)
    
    # This effect produces a certain amount of score
    # per building of the kinds "kinds_scored" built by 2 neighbours and/or player
    kinds_scored = models.ManyToManyField(BuildingKind, blank=True, null=True, related_name='score_benefiting_effects')
    score_per_neighbor_building = models.PositiveIntegerField(default=0)
    score_per_local_building = models.PositiveIntegerField(default=0)
    
    # Effects that give bonus money (instant) or score depending on the number
    # of special builts (local and/or by neighbors)
    money_per_local_special = models.PositiveIntegerField(default=0)
    score_per_local_special = models.PositiveIntegerField(default=0)
    money_per_neighbor_special = models.PositiveIntegerField(default=0)
    score_per_neighbor_special = models.PositiveIntegerField(default=0)

    # extra score per neighbor defeats 
    score_per_neighbor_defeat = models.PositiveIntegerField(default=0)

    # Special effects
    free_building = models.BooleanField()
    extra_turn = models.BooleanField()
    use_discards = models.BooleanField()
    copy_personality = models.BooleanField()
    

class CitySpecial(models.Model):
    """
    A special effect that can be built in a single city/variant of a city
    """
    city = models.ForeignKey(City)
    variant = models.ForeignKey(Variant)
    order = models.PositiveIntegerField() # Order in which the special needs to be built (specials are always built from lower to higher). 0-based
    cost = models.ForeignKey(Cost)
    effect = models.ForeignKey(Effect)
    
    class Meta:
        unique_together = (
            ('city', 'variant', 'order'),
        )
        ordering = ('city', 'variant', 'order')

class Building(models.Model):
    """
    What a player can put in cities to have its effects applied
    """
    name = models.CharField(max_length=30)
    kind = models.ForeignKey(BuildingKind)
    effect = models.ForeignKey(Effect)

    cost = models.ForeignKey(Cost)
    free_having = models.ForeignKey('self') # This models is free when having other bulding

    class Meta:
        ordering = ('name',)

class BuildOption(models.Model):
    """An item allowing to create a specific bulding on a phase"""
    players_needed = models.PositiveIntegerField()
    building = models.ForeignKey(Building)
    age = models.ForeignKey(Age)
    
    