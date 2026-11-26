"""Offline regression tests for title matching. No API credentials required."""
import unittest
from unittest.mock import patch
from collections import Counter
import steamgriddb_index as s

class SearchTests(unittest.TestCase):
    def test_short_title(self):
        self.assertIn('!click!',s.variants(['!click! (USA)']))
        self.assertIn('click',s.variants(['!click! (USA)']))
    def test_articles(self):
        self.assertEqual(s.clean_title('Legend of Zelda, The (USA)'), 'The Legend of Zelda')
    def test_subtitle(self):
        self.assertEqual(s.clean_title('A Game (Special Edition)'), 'A Game (Special Edition)')
    def test_alternate_title(self):
        self.assertIn('Alternate Name',s.variants(['Original Name','Alternate Name']))
    def test_sequel(self):
        self.assertEqual(s.equivalent_key('Game II'),s.equivalent_key('Game 2'))
        self.assertNotEqual(s.equivalent_key('Game II'),s.equivalent_key('Game III'))
    def test_multiplatform_requires_verified(self):
        self.assertFalse(s.acceptable_hit({'id':1,'name':'Game'}, {'game'},True))
        self.assertTrue(s.acceptable_hit({'id':1,'name':'Game','verified':True}, {'game'},True))
    def test_portrait_and_safety_filters(self):
        url='https://cdn.steamgriddb.com/grid/example.png'
        stats=Counter()
        with patch.object(s,'api',side_effect=[
            [{'id':1,'name':'!click!'}],
            [{'url':url,'width':500,'height':750,'nsfw':True,'humor':False},
             {'url':url,'width':500,'height':750,'nsfw':False,'humor':False}]
        ]) as api:
            self.assertEqual(s.find(['!click!'],'test-key',stats),[url])
            self.assertNotIn('dimensions=',api.call_args_list[1].args[0])
    def test_ambiguity(self):
        stats=Counter()
        with patch.object(s,'api',return_value=[{'id':1,'name':'Game'},{'id':2,'name':'Game'}]):
            self.assertEqual(s.find(['Game'],'test-key',stats),[])
        self.assertEqual(stats['ambiguous_title'],1)

if __name__=='__main__': unittest.main()
