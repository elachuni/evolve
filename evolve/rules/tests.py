import mock

from django.test import TestCase
from evolve.rules import models

class ScoreTest(TestCase):

    def setUp(self):
        self.score = models.Score.new()

    def test_correct_count(self):
        self.assertEqual(len(self.score), 7)

    def test_correct_values(self):
        self.assertTrue(all(value==0 for value in self.score))
        
    def test_set_attributes(self):
        """Tests setting the 7 relevant attributes with _replace() """
        score = self.score._replace(treasury=1, military=2, special=3, civilian=4)
        score = score._replace(economy=5, science=6, personality=7)
        self.assertEqual(score, (1,2,3,4,5,6,7))
    
    def test_add(self):
        s2 = models.Score(1,3,5,7,2,4,6)
        s3 = models.Score(3,3,3,3,3,3,3)
        result = self.score + s2 + s3
        self.assertEqual(result, (4,6,8,10,5,7,9))


    def test_total(self):
        s = models.Score(4,6,8,10,5,7,9)
        result = s.total()
        self.assertEqual(result, 49)

class BuildingKindTest(TestCase):

    def test_unicode(self):
        bk = models.BuildingKind(name=models.PERSONALITY)
        self.assertNotEqual(unicode(bk), '')

class ResourceTest(TestCase):

    def test_unicode(self):
        r = models.Resource(name=u'Test Resource')
        self.assertEqual(unicode(r), u'Test Resource')


class ScienceTest(TestCase):

    def test_unicode(self):
        s = models.Science(name=u'Test Science')
        self.assertEqual(unicode(s), u'Test Science')

class VariantTest(TestCase):

    def test_unicode(self):
        s = models.Variant(label=u'Test Variant')
        self.assertEqual(unicode(s), u'Test Variant')

class AgeTest(TestCase):

    def setUp(self):
        self.a1 = models.Age.objects.create(
            name='test age 1',
            order=0,
            direction='l',
            victory_score=1
        )
        self.a2 = models.Age.objects.create(
            name='test age 2',
            order=1,
            direction='l',
            victory_score=1
        )

    def test_first(self):
        first_age = models.Age.first()
        self.assertEqual(first_age, self.a1)

    def test_next(self):
        next_age = self.a1.next()
        self.assertEqual(next_age, self.a2)
    
    def test_next_after_final(self):
        next_age = self.a2.next()
        self.assertIs(next_age, None)
    
    def test_unicode(self):
        self.assertEqual(unicode(self.a1), u'test age 1')

class EmptyCostTest(TestCase):
    
    def setUp(self):
        self.cost = models.Cost()
    
    def test_to_dict(self):
        self.cost.money = 7
        d = self.cost.to_dict()
        self.assertEqual(d, {'$': 7})

    def test_to_list(self):
        self.cost.money = 7
        l = self.cost.to_list()
        self.assertEqual(l, [])

    def test_unicode_free(self):
        self.assertEqual(unicode(self.cost), 'Free')

    def test_unicode_non_free(self):
        self.cost.money = 7
        # Do not need a specific formatting, but shouldn't bee blatantly wrong
        # or invisible
        self.assertNotEqual(unicode(self.cost), 'Free')
        self.assertNotEqual(unicode(self.cost), '')

class NonEmptyCostTest(TestCase):
    
    def setUp(self):
        self.cost = models.Cost.objects.create()
        self.resource_1 = models.Resource.objects.create(name='R1')
        self.resource_2 = models.Resource.objects.create(name='R2')
        self.cost_line_1 = models.CostLine.objects.create(cost=self.cost, amount=2, resource=self.resource_1)
        self.cost_line_2 = models.CostLine.objects.create(cost=self.cost, amount=3, resource=self.resource_2)
    
    def test_to_dict(self):
        d = self.cost.to_dict()
        self.assertEqual(d, {'$': 0, 'R1': 2, 'R2': 3})

    def test_to_list(self):
        self.cost.money = 7
        l = self.cost.to_list()
        self.assertEqual(set(l), set([(2, u'R1'), (3, u'R2')]))

    def test_unicode_non_free(self):
        # Do not need a specific formatting, but shouldn't bee blatantly wrong
        # or invisible
        self.assertNotEqual(unicode(self.cost), 'Free')
        self.assertNotEqual(unicode(self.cost), '')

class CityTest(TestCase):

    def test_unicode(self):
        c = models.City(name=u'Test City')
        self.assertEqual(unicode(c), u'Test City')

def mock_player(specials, defeats, kinds):
    result = mock.Mock()
    result.specials.return_value = specials
    result.defeats.return_value = defeats
    result.count.side_effect = lambda kind: kinds.get(kind.name, 0)
    return result

class EffectTest(TestCase):

    def setUp(self):
        self.bk_mil = models.BuildingKind(name='mil')
        self.bk_mil.save()
        self.bk_civ = models.BuildingKind(name='civ')
        self.bk_civ.save()
        self.bk_sci = models.BuildingKind(name='sci')
        self.bk_sci.save()

    def should_be_clean(self, effect):
        try:
            effect.clean()
        except models.ValidationError:
            self.fail("clean() on an effect raised ValidationError and shouldn't")

    def test_clean_simple(self):
        e = models.Effect()
        self.should_be_clean(e)
            
    def test_clean_trade(self):
        e = models.Effect(trade=models.Cost(), left_trade=1)
        self.should_be_clean(e)
        e = models.Effect(trade=models.Cost(), right_trade=1)
        self.should_be_clean(e)
        e = models.Effect(trade=models.Cost(), left_trade=1, right_trade=1)
        self.should_be_clean(e)

    def test_clean_pay(self):
        e = models.Effect(kind_payed=models.BuildingKind(), money_per_local_building=1)
        self.should_be_clean(e)
        e = models.Effect(kind_payed=models.BuildingKind(), money_per_neighbor_building=1)
        self.should_be_clean(e)
        e = models.Effect(kind_payed=models.BuildingKind(), money_per_local_building=1, money_per_neighbor_building=1)
        self.should_be_clean(e)

    def test_unclean_trade(self):
        e = models.Effect(trade=models.Cost(), left_trade=0, right_trade=0)
        with self.assertRaises(models.ValidationError):
            e.clean()
        e = models.Effect(trade=None, left_trade=3, right_trade=0)
        with self.assertRaises(models.ValidationError):
            e.clean()
        
    def test_unclean_pay(self):
        e = models.Effect(kind_payed=models.BuildingKind(), money_per_local_building=0, money_per_neighbor_building=0)
        with self.assertRaises(models.ValidationError):
            e.clean()
        e = models.Effect(kind_payed=None, money_per_local_building=0, money_per_neighbor_building=2)
        with self.assertRaises(models.ValidationError):
            e.clean()
        
    def test_money_from_production(self):
        e = models.Effect(production=models.Cost(money=3))
        p = mock_player(1, 1, {'civ': 1})
        money = e.money(p, p, p)
        self.assertEqual(money, 3)
        
    def test_money_per_neighbor_building(self):
        e = models.Effect(kind_payed=self.bk_civ, money_per_neighbor_building=2)
        p1 = mock_player(1, 1, {'civ': 1, 'mil': 4})
        p2 = mock_player(1, 1, {'civ': 2, 'mil': 4})
        p3 = mock_player(1, 1, {'civ': 3, 'mil': 4})
        money = e.money(p1, p2, p3)
        self.assertEqual(money, 10) # 2 * (2+3)

    def test_money_per_local_building(self):
        e = models.Effect(kind_payed=self.bk_civ, money_per_local_building=3)
        p1 = mock_player(1, 1, {'civ': 2, 'mil': 4})
        p2 = mock_player(1, 1, {'civ': 5, 'mil': 4})
        money = e.money(p1, p2, p2)
        self.assertEqual(money, 6) # 3 * 2

    def test_money_per_neighbor_special(self):
        e = models.Effect(money_per_neighbor_special=2)
        p1 = mock_player(1, 1, {'civ': 1, 'mil': 4})
        p2 = mock_player(3, 1, {'civ': 2, 'mil': 4})
        p3 = mock_player(5, 1, {'civ': 3, 'mil': 4})
        money = e.money(p1, p2, p3)
        self.assertEqual(money, 16) # 2 * (3+5)

    def test_money_per_local_special(self):
        e = models.Effect(money_per_local_special=2)
        p1 = mock_player(1, 1, {'civ': 1, 'mil': 4})
        p2 = mock_player(3, 1, {'civ': 2, 'mil': 4})
        money = e.money(p1, p2, p2)
        self.assertEqual(money, 2) # 2 * 1

    def test_money_effects_accumulate(self):
        e = models.Effect(
            production=models.Cost(money=3),
            kind_payed=self.bk_civ,
            money_per_neighbor_building=2,
            money_per_local_building=3,
            money_per_neighbor_special=2,
            money_per_local_special=1
        )
        p1 = mock_player(1, 1, {'civ': 1, 'mil': 4})
        p2 = mock_player(3, 1, {'civ': 2, 'sci': 4})
        p3 = mock_player(5, 1, {'civ': 3})
        money = e.money(p1, p2, p3)
        self.assertEqual(money, 33) # 3 + 2 * (2+3) + 3*1 + 2*(3+5) + 1*1
    
    # TODO: score tests
