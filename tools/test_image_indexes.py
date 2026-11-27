import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from collections import defaultdict
import art_index as art
import launchbox_index as lb
from build import base_title, norm, write_json

class ImageIndexesTests(unittest.TestCase):
    def test_libretro_platform_alias_and_title_alias(self):
        names={'Named_Boxarts':['Known Alternate'],'Named_Titles':[],'Named_Snaps':[]}
        system='Microsoft - XBOX'
        merged={system:{'Canonical Title'}}
        aliases={system:{base_title('Known Alternate'):base_title('Canonical Title')}}
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            with patch.object(art,'module_map',return_value={'Microsoft - Xbox':('sample','master')}),patch.object(art,'files_for',return_value=names):
                result,stats=art.index_games(out,merged,base_title,write_json,aliases)
            self.assertEqual(stats['art_matches'],1)
            self.assertEqual(json.loads((out/result[system]).read_text())['rows']['Canonical Title'][1],'Known Alternate')

    def test_libretro_digital_platform(self):
        names={'Named_Boxarts':['Known Game'],'Named_Titles':[],'Named_Snaps':[]}
        system='Sony - PlayStation 3 (PSN)'
        with tempfile.TemporaryDirectory() as d:
            with patch.object(art,'module_map',return_value={'Sony - PlayStation 3':('sample','master')}),patch.object(art,'files_for',return_value=names):
                result,stats=art.index_games(Path(d),{system:{'Known Game'}},base_title,write_json)
            self.assertEqual(stats['art_matches'],1)

    def test_launchbox_image_only_preserves_catalog_and_groups(self):
        system='Nintendo - Nintendo Entertainment System'
        merged=defaultdict(set,{system:{'Known Alternate','Existing Game'}})
        data={'schema':4,'platforms':{system:[
            ['Canonical Game',['Known Alternate'],[['abcdefghij.png',0,'World']]],
            ['Unlisted Game',[],[['klmnopqrst.png',0,'World']]]
        ]},'rom_hacks':{system:['Existing Game']}}
        before={k:set(v) for k,v in merged.items()}
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            with patch.object(lb,'load_index',return_value=(data,'test')):
                result,aliases,stats=lb.apply_index(out,merged,[],base_title,norm,write_json,lambda n:False,images_only=True)
            self.assertEqual(dict(merged),before)
            self.assertEqual(stats['launchbox_added_titles'],0)
            self.assertEqual(stats['launchbox_hacks_removed_from_catalog'],0)
            self.assertEqual(set(json.loads((out/result[system]).read_text())),{'Known Alternate'})
            self.assertFalse((out/'data/groups').exists())

if __name__=='__main__': unittest.main()
