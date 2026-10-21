"""Download the two OpenCV Zoo models and cut MobileNetV2 at its pooling layer.

    python make_features_model.py

OpenCV 5's new DNN engine only returns a network's final output, so the 1280-number feature vector
(before the 1000-class ImageNet layer) has to be the graph's output. Models are Apache-2.0 / MIT
(opencv_zoo).
"""
import urllib.request

import cv2
import numpy as np
import onnx

from ww_vision.pipeline import MODELS

ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models/"
FILES = {
    "image_classification_mobilenetv2_2022apr.onnx": "image_classification_mobilenet/",
    "face_detection_yunet_2023mar.onnx": "face_detection_yunet/",
}

MODELS.mkdir(exist_ok=True)
for name, folder in FILES.items():
    if not (MODELS / name).exists():
        urllib.request.urlretrieve(ZOO + folder + name, MODELS / name)

m = onnx.load(str(MODELS / "image_classification_mobilenetv2_2022apr.onnx"))
names = [n.name for n in m.graph.node]
pool = m.graph.node[names.index("GlobalAveragePool_97")]
del m.graph.node[names.index(pool.name) + 1:]
del m.graph.output[:]
m.graph.output.append(onnx.helper.make_tensor_value_info(pool.output[0], onnx.TensorProto.FLOAT, [1, 1280, 1, 1]))
onnx.checker.check_model(m)
onnx.save(m, str(MODELS / "mobilenetv2_features.onnx"))

net = cv2.dnn.readNetFromONNX(str(MODELS / "mobilenetv2_features.onnx"))
net.setInput(cv2.dnn.blobFromImage(np.zeros((224, 224, 3), np.uint8), 1 / 255.0, (224, 224)))
assert net.forward().shape == (1, 1280, 1, 1)
print("models ready in", MODELS)
