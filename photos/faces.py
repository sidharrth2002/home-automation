"""Faces in a photo, on this machine: OpenCV's YuNet to find them and SFace to recognise one person (you).

Runs on the ~800px thumbnail, never the original. Nothing leaves the machine: the models are in data/photos/models/
and your reference face (an embedding made from one photo of you) is data/photos/me.npy, all git-ignored.
"""
import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("photos.faces")
ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "data" / "photos" / "models"
ME = ROOT / "data" / "photos" / "me.npy"
DETECTOR = MODELS / "face_detection_yunet_2023mar.onnx"
RECOGNISER = MODELS / "face_recognition_sface_2021dec.onnx"
SAME_PERSON = 0.363  # SFace's recommended cosine threshold
MIN_FACE = 0.045  # a face smaller than this fraction of the image height is background, not someone in the photo


class Faces:
    def __init__(self):
        self.detector = cv2.FaceDetectorYN.create(str(DETECTOR), "", (320, 320), 0.8, 0.3, 50)
        self.recogniser = cv2.FaceRecognizerSF.create(str(RECOGNISER), "")
        self.me = np.load(ME) if ME.exists() else None

    def _detect(self, img):
        h, w = img.shape[:2]
        self.detector.setInputSize((w, h))
        found = self.detector.detect(img)[1]
        return [] if found is None else list(found)

    def embed(self, img, face) -> np.ndarray:
        return self.recogniser.feature(self.recogniser.alignCrop(img, face))

    def analyse(self, jpeg: bytes) -> dict:
        """People in the photo (faces big enough to be the subject), whether you're one of them, and basic quality."""
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return {"ok": False}
        h, w = img.shape[:2]
        faces = [f for f in self._detect(img) if f[3] / h >= MIN_FACE]
        largest = max((f[2] * f[3] / (w * h) for f in faces), default=0.0)
        me = False
        if self.me is not None:
            for f in faces:
                if self.recogniser.match(self.me, self.embed(img, f), cv2.FaceRecognizerSF_FR_COSINE) >= SAME_PERSON:
                    me = True
                    break
        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return {"ok": True, "faces": len(faces), "largest_face": round(float(largest), 4), "me": me,
                "sharpness": round(float(cv2.Laplacian(grey, cv2.CV_64F).var()), 1),
                "brightness": round(float(grey.mean()), 1), "landscape": w >= h}

    def learn_me(self, image_path: Path) -> bool:
        """Make the reference embedding from a photo of you (the largest face in it)."""
        img = cv2.imread(str(image_path))
        if img is None:
            return False
        img = cv2.resize(img, None, fx=min(1.0, 1280 / max(img.shape[:2])), fy=min(1.0, 1280 / max(img.shape[:2])))
        faces = self._detect(img)
        if not faces:
            return False
        face = max(faces, key=lambda f: f[2] * f[3])
        ME.parent.mkdir(parents=True, exist_ok=True)
        np.save(ME, self.embed(img, face))
        self.me = np.load(ME)
        return True
