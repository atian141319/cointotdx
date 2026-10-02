import struct
import unittest
from chart_refresh import observed_period, reload_active


def bitmap():
    size=1024*526*4
    return bytearray(struct.pack('<2sIHHI',b'BM',54+size,0,0,54)+
                     struct.pack('<IiiHHIIIIII',40,1024,526,1,32,0,size,0,0,0,0)+bytes(size))


class RefreshGuards(unittest.TestCase):
    def test_unknown_and_ambiguous_selection_refuse_click(self):
        raw=bitmap()
        with self.assertRaises(ValueError):observed_period(raw)
        for x in range(100,132):
            p=54+((525-37)*1024+x)*4
            raw[p:p+4]=bytes((255,255,0,0))
        self.assertEqual(observed_period(raw),'5m')
        for x in range(145,177):
            p=54+((525-37)*1024+x)*4
            raw[p:p+4]=bytes((255,255,0,0))
        with self.assertRaises(ValueError):observed_period(raw)

    def test_changed_layout_or_truncated_bitmap_is_rejected(self):
        raw=bitmap()
        with self.assertRaises(ValueError):observed_period(raw[:-4])
        struct.pack_into('<i',raw,18,1280)
        with self.assertRaises(ValueError):observed_period(raw)

    def test_unowned_chart_is_not_operated_on(self):
        class FakeClient:
            def windows(self):return [(1,'通达信金融终端V7.73 - [分析图表-EURUSD]',2)]
            def capture(self,path):raise AssertionError('Do not capture unrelated instrument')
            def period(self,value):raise AssertionError('Do not click unrelated instrument')
        result=reload_active(FakeClient(),[{'enabled':True,'display_name':'ETHUSDT试验','symbol':'ETHUSDT','code':'397903'}])
        self.assertFalse(result['requested'])


if __name__=='__main__':unittest.main()
