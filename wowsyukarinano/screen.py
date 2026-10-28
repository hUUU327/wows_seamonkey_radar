"""Any screen resolution mapped to the 1920x1080 layout the recognizers work in.

The game scales its interface with the screen height, so a frame is scaled to 1080 rows and centred on
1920 columns (narrower screens padded, wider ones cropped at the sides). At 1920x1080 this is a no-op.
"""
import cv2
import numpy as np

REF_W, REF_H = 1920, 1080
# corner blocks in the 1080p layout (x0, y0, x1, y1), anchored to the left / right screen edge: the
# corners hold the game's own panels, which do not move with the centring above
LEFT_BLOCK = (0, 640, 440, 1080)
RIGHT_BLOCK = (1500, 660, 1920, 1080)


class ScreenGeometry:
    def __init__(self, width, height):
        self.w, self.h = int(width), int(height)
        self.scale = self.h / REF_H                      # screen px per 1080p px
        self.wn = int(round(self.w / self.scale))        # normalized width before centring
        self.pad = (REF_W - self.wn) // 2                # + = padded, - = cropped (per side)
        self.identity = (self.w, self.h) == (REF_W, REF_H)

    def normalize(self, img):
        """A screen frame (BGR or gray) in the 1920x1080 layout."""
        if self.identity:
            return img
        scaled = cv2.resize(img, (self.wn, REF_H), interpolation=cv2.INTER_AREA)
        out = np.zeros((REF_H, REF_W) + img.shape[2:], img.dtype)
        if self.pad >= 0:
            out[:, self.pad:self.pad + self.wn] = scaled
        else:
            out[:] = scaled[:, -self.pad:-self.pad + REF_W]
        x0, y0, x1, y1 = LEFT_BLOCK
        out[y0:y1, x0:x1] = scaled[y0:y1, x0:x1]
        x0, y0, x1, y1 = RIGHT_BLOCK
        out[y0:y1, x0:x1] = scaled[y0:y1, self.wn - (REF_W - x0):self.wn]
        return out
