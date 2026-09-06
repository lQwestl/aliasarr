import os
import struct
import tempfile
import unittest

from app.services.media_probe import (
    classify_resolution,
    _map_vcodec,
    _map_acodec,
    _map_channels,
    probe_media_file,
    _probe_mkv_pure_python,
    _probe_mp4_pure_python,
    _probe_avi_pure_python,
)
from app.services.quality import detect_file_quality, parse_quality


class TestMediaProbe(unittest.TestCase):

    def test_classify_resolution(self):
        # 4K / UHD
        self.assertEqual(classify_resolution(3840, 2160), "2160p")
        self.assertEqual(classify_resolution(3840, 1600), "2160p")

        # 1080p (включая 1440x1080 4:3 BDRip и 1920x800 letterbox)
        self.assertEqual(classify_resolution(1440, 1080), "1080p")
        self.assertEqual(classify_resolution(1920, 1080), "1080p")
        self.assertEqual(classify_resolution(1920, 800), "1080p")

        # 720p (включая 960x720 4:3 и 1280x534)
        self.assertEqual(classify_resolution(1280, 720), "720p")
        self.assertEqual(classify_resolution(960, 720), "720p")
        self.assertEqual(classify_resolution(1280, 534), "720p")

        # 576p (PAL)
        self.assertEqual(classify_resolution(720, 576), "576p")

        # 480p (NTSC / SD)
        self.assertEqual(classify_resolution(720, 480), "480p")
        self.assertEqual(classify_resolution(640, 480), "480p")

    def test_codecs_and_channels_mapping(self):
        self.assertEqual(_map_vcodec("V_MPEG4/ISO/AVC"), "x264")
        self.assertEqual(_map_vcodec("avc1"), "x264")
        self.assertEqual(_map_vcodec("V_MPEGH/ISO/HEVC"), "HEVC")
        self.assertEqual(_map_vcodec("hev1"), "HEVC")
        self.assertEqual(_map_vcodec("av01"), "AV1")
        self.assertEqual(_map_vcodec("vp09"), "VP9")

        self.assertEqual(_map_acodec("A_AC3"), "AC3")
        self.assertEqual(_map_acodec("A_EAC3"), "EAC3")
        self.assertEqual(_map_acodec("A_DTS"), "DTS")
        self.assertEqual(_map_acodec("A_AAC"), "AAC")
        self.assertEqual(_map_acodec("A_FLAC"), "FLAC")
        self.assertEqual(_map_acodec("A_TRUEHD"), "TrueHD")

        self.assertEqual(_map_channels(8), "7.1")
        self.assertEqual(_map_channels(6), "5.1")
        self.assertEqual(_map_channels(2), "2.0")
        self.assertEqual(_map_channels(1), "1.0")

    def test_pure_python_avi_probe(self):
        # Строим минимальный RIFF AVI заголовок
        # 0x00: RIFF (4) + size (4) + AVI  (4)
        # LIST (4) + size (4) + hdrl (4) + avih (4) + avih_size (4) + 32 bytes + width(4) + height(4)
        avi_data = bytearray(b"RIFF\x00\x01\x00\x00AVI LIST\x00\x00\x00\x00hdrlavih\x38\x00\x00\x00")
        avi_data.extend(b"\x00" * 32)
        avi_data.extend(struct.pack("<I", 1440))  # width = 1440
        avi_data.extend(struct.pack("<I", 1080))  # height = 1080
        avi_data.extend(b"\x00" * 64)

        with tempfile.NamedTemporaryFile(suffix=".avi", delete=False) as f:
            f.write(avi_data)
            temp_path = f.name

        try:
            res = _probe_avi_pure_python(temp_path)
            self.assertIsNotNone(res)
            self.assertEqual(res["resolution"], "1080p")
            self.assertEqual(res["width"], 1440)
            self.assertEqual(res["height"], 1080)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_pure_python_mp4_probe(self):
        # Строим минимальный MP4 файл с moov -> trak -> tkhd
        # tkhd version 0: 84 bytes, width at offset 76, height at offset 80 (16.16 fixed point)
        tkhd_payload = bytearray(b"\x00" * 84)
        # width = 1920 (0x07800000), height = 1080 (0x04380000)
        tkhd_payload[76:80] = struct.pack(">I", 1920 << 16)
        tkhd_payload[80:84] = struct.pack(">I", 1080 << 16)
        tkhd_atom = struct.pack(">I", len(tkhd_payload) + 8) + b"tkhd" + bytes(tkhd_payload)

        # stsd atom с кодеком avc1
        stsd_payload = b"\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00 avc1" + b"\x00" * 30
        stsd_atom = struct.pack(">I", len(stsd_payload) + 8) + b"stsd" + stsd_payload
        stbl_atom = struct.pack(">I", len(stsd_atom) + 8) + b"stbl" + stsd_atom
        minf_atom = struct.pack(">I", len(stbl_atom) + 8) + b"minf" + stbl_atom
        mdia_atom = struct.pack(">I", len(minf_atom) + 8) + b"mdia" + minf_atom

        trak_content = tkhd_atom + mdia_atom
        trak_atom = struct.pack(">I", len(trak_content) + 8) + b"trak" + trak_content
        moov_atom = struct.pack(">I", len(trak_atom) + 8) + b"moov" + trak_atom

        ftyp_atom = struct.pack(">I", 20) + b"ftypisom\x00\x00\x02\x00isom"
        mp4_data = ftyp_atom + moov_atom

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(mp4_data)
            temp_path = f.name

        try:
            res = _probe_mp4_pure_python(temp_path)
            self.assertIsNotNone(res)
            self.assertEqual(res["resolution"], "1080p")
            self.assertEqual(res["width"], 1920)
            self.assertEqual(res["height"], 1080)
            self.assertEqual(res["video_codec"], "x264")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_pure_python_mkv_probe(self):
        # EBML Header (0x1A45DFA3) + Segment (0x18538067) + Tracks (0x1654AE6B) + TrackEntry (0xAE)
        # Внутри TrackEntry: Video (0xE0) -> PixelWidth (0xB0, 1440), PixelHeight (0xBA, 1080), CodecID (0x86, "V_MPEG4/ISO/AVC")
        # Audio (0xE1) -> Channels (0x9F, 2), CodecID (0x86, "A_AC3")
        width_bytes = struct.pack(">H", 1440)
        height_bytes = struct.pack(">H", 1080)
        video_sub = (
            b"\xb0\x82" + width_bytes +   # 0xB0 (PixelWidth), vint len 2
            b"\xba\x82" + height_bytes     # 0xBA (PixelHeight), vint len 2
        )
        video_elem = b"\xe0" + bytes([0x80 | len(video_sub)]) + video_sub
        v_codec = b"\x86\x8fV_MPEG4/ISO/AVC"  # 0x86 (CodecID), len 15

        track1 = video_elem + v_codec
        track_entry1 = b"\xae" + bytes([0x80 | len(track1)]) + track1

        audio_sub = b"\x9f\x81\x02"  # 0x9F (Channels = 2)
        audio_elem = b"\xe1" + bytes([0x80 | len(audio_sub)]) + audio_sub
        a_codec = b"\x86\x85A_AC3"
        track2 = audio_elem + a_codec
        track_entry2 = b"\xae" + bytes([0x80 | len(track2)]) + track2

        tracks_content = track_entry1 + track_entry2
        tracks_elem = b"\x16\x54\xae\x6b" + bytes([0x80 | len(tracks_content)]) + tracks_content

        segment_elem = b"\x18\x53\x80\x67" + bytes([0x80 | len(tracks_elem)]) + tracks_elem
        ebml_hdr = b"\x1a\x45\xdf\xa3\x84\x42\x82\x88mkv"
        mkv_data = ebml_hdr + segment_elem

        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as f:
            f.write(mkv_data)
            temp_path = f.name

        try:
            res = _probe_mkv_pure_python(temp_path)
            self.assertIsNotNone(res)
            self.assertEqual(res["resolution"], "1080p")
            self.assertEqual(res["width"], 1440)
            self.assertEqual(res["height"], 1080)
            self.assertEqual(res["video_codec"], "x264")
            self.assertEqual(res["audio_codec"], "AC3")
            self.assertEqual(res["audio_channels"], "2.0")

            # Тестируем интеграцию с detect_file_quality
            q_info = detect_file_quality(temp_path, context_hints=["Cyber City Oedo 808 [1990] [BDRip]"], probe_file=True)
            self.assertEqual(q_info.name, "Bluray-1080p")
            self.assertEqual(q_info.resolution, "1080p")
            self.assertEqual(q_info.video_codec, "x264")
            self.assertEqual(q_info.audio_codec, "AC3")
            self.assertEqual(q_info.audio_channels, "2.0")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_detect_file_quality_with_hints(self):
        # Проверяем случай Cyber City Oedo 808
        hints = [
            "Кибер-город Эдо 808 / Cyber City Oedo 808 [OVA] [E3 of 3] [RUS(ext), ENG, JAP+Sub] [1990, боевик, фантастика, киберпанк, BDRip] [1080p]"
        ]
        q = detect_file_quality("/downloads/Cyber City Oedo 808 [1990]/01-Memories of the Past.mkv", context_hints=hints, probe_file=False)
        self.assertEqual(q.name, "Bluray-1080p")
        self.assertEqual(q.resolution, "1080p")
        self.assertEqual(q.source, "Bluray")


if __name__ == "__main__":
    unittest.main()
