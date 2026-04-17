import cv2, numpy as np, sys
sys.path.insert(0, '.')
from src.scanner.omr import _score_arc_presence, _edge_density_score

img = cv2.imread('data/processed/CamScanner 4-14-26 10.04_page08.jpg', cv2.IMREAD_GRAYSCALE)

centers = {'1':(418,202),'2':(417,247),'3':(418,299),
           '4':(418,348),'5':(698,195),'6':(696,247),
           '7':(698,299),'8':(698,348)}

print('Testing different radii for S8_age_Q1:')
for radius in [20, 30, 40, 50, 60]:
    print(f'  radius={radius}:')
    for val, (cx, cy) in centers.items():
        roi = img[cy-radius:cy+radius, cx-radius:cx+radius]
        arc = _score_arc_presence(roi)
        edge = _edge_density_score(roi)
        print(f'    option {val}: arc={arc:.3f} edge={edge:.3f}')
