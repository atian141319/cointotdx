from pathlib import Path
import json
import struct
import tempfile
import unittest
from unittest.mock import patch
from external_registry import register, check
from settings import default_settings, validate
from display import Publisher, encode


class ExternalRegistryTests(unittest.TestCase):
    def fixture(self, folder):
        root = Path(folder)
        config = default_settings()
        config['tdx'] = {'installation':str(root/'client'), 'executable':str(root/'client/tdxw.exe'),
                         'data_directory':str(root/'client/vipdoc')}
        config['data_directory'] = str(root/'exact')
        pair = dict(config['pairs'][0], symbol='ETHUSDT', code='397903', market='ds', market_id=10)
        config['pairs'] = [pair]
        registry = root/'client/T0002/hq_cache/ds_stk.dat'
        registry.parent.mkdir(parents=True)
        raw = bytearray(106)
        raw[:5] = bytes.fromhex('040a050000')
        raw[5:11] = b'EURUSD'
        raw[28:38] = '\u6b27\u5143\u5151\u7f8e\u5143'.encode('gbk')
        registry.write_bytes(raw)
        from session_config import NATIVE_10
        registry.with_name('ds_tinf.dat').write_bytes(bytes([10]) + b'?' * 8 + b'\0' + struct.pack('<10HI', *NATIVE_10, 1))
        return config, pair, registry

    @patch('client_control.Client.windows', return_value=[])
    def test_append_idempotence_owned_identity_and_collision(self, windows):
        with tempfile.TemporaryDirectory() as folder:
            config,pair,registry=self.fixture(folder)
            original=registry.read_bytes();register(config,[pair]);registered=registry.read_bytes()
            self.assertTrue(registered.startswith(original));self.assertTrue(check(config['tdx']['installation'],pair)[0])
            register(config,[pair]);self.assertEqual(registry.read_bytes(),registered)
            other=dict(pair,symbol='SOLUSDT')
            with self.assertRaises(ValueError):register(config,[other])
            registry.write_bytes(original)
            self.assertFalse(check(config['tdx']['installation'],pair)[0])

    @patch('client_control.Client.windows', return_value=[(1,'client',1)])
    def test_registration_refuses_running_client(self, windows):
        with tempfile.TemporaryDirectory() as folder:
            config,pair,registry=self.fixture(folder);original=registry.read_bytes()
            with self.assertRaises(ValueError):register(config,[pair])
            self.assertEqual(registry.read_bytes(),original)

    @patch('client_control.Client.windows', return_value=[])
    def test_external_paths_and_float_day_publication(self, windows):
        with tempfile.TemporaryDirectory() as folder:
            config,pair,registry=self.fixture(folder);register(config,[pair])
            validate(config,check_paths=False)
            publisher=Publisher(config,lambda **s:None)
            self.assertEqual(publisher.targets(pair)['5m'].name,'10#397903.lc5')
            row=[1790812800000,'1.01','1.03','1','1.02','0.6',1790899199999,'12.34567890',1,'0','0','0']
            publisher.queue(pair,'1d',[row]);self.assertTrue(publisher.flush())
            raw=publisher.targets(pair)['1d'].read_bytes()
            self.assertAlmostEqual(struct.unpack('<IfffffII',raw)[1],1.01,places=6)
            self.assertEqual(struct.unpack('<IfffffII',raw)[6],0)
            publisher.restore();self.assertFalse(publisher.targets(pair)['1d'].exists())
