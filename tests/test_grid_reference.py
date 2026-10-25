"""Offline decoder-reference checks; synthetic only, no device access."""
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from native_grid_vectors import reference


def heads(size=32):
    return [dict(w=size//s,h=size//s,stride=s,scale=1/255,zp=-128,
        anchors=[(8,8)]*3,cells={}) for s in (8,16,32)]


def raw(cls):
    values=[0]*4+[127]+[-128]*7
    values[5+cls]=127
    return values


class GridReferenceTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(reference(heads(),32,32),[])

    def test_class_aware_conflict(self):
        h=heads()
        h[0]['cells']={(0,1,1):raw(1),(1,1,1):raw(1),(2,1,1):raw(2)}
        result=reference(h,32,32)
        self.assertEqual([item[2] for item in result],[1,2])
        self.assertAlmostEqual(result[0][1],1)

    def test_tie_lower_class(self):
        h=heads();values=raw(6);values[6]=127
        h[0]['cells'][(0,1,1)]=values
        self.assertEqual(reference(h,32,32)[0][2],1)

    def test_probability_product_threshold(self):
        h=heads();values=raw(0);values[4]=-64 # objectness 64/255, class score 1
        h[0]['cells'][(0,1,1)]=values
        self.assertEqual(reference(h,32,32),[])
        self.assertEqual(len(reference(h,32,32,threshold=.2)),1)

    def test_crowded_frame_fails_not_topk(self):
        h=heads(96)
        for head in h:
            head['cells']={(a,y,x):raw(0) for a in range(3)
                           for y in range(head['h']) for x in range(head['w'])}
        self.assertIsNone(reference(h,96,96))
