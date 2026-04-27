from __future__ import annotations

import unittest

from hockey_app.ui.components import logo_bank as logo_bank_mod


@unittest.skipUnless(logo_bank_mod.PIL_OK, "Pillow is required for logo alpha tests")
class LogoBankTests(unittest.TestCase):
    def test_apply_dim_rgba_scales_alpha_channel(self) -> None:
        img = logo_bank_mod.Image.new("RGBA", (1, 1), (255, 255, 255, 200))  # type: ignore[union-attr]

        out = logo_bank_mod._apply_dim_rgba(img, 0.5)

        self.assertEqual(out.getpixel((0, 0))[3], 100)


if __name__ == "__main__":
    unittest.main()
