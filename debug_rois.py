import cv2, numpy as np

img = cv2.imread('data/processed/CamScanner 4-14-26 10.04_page08.jpg', cv2.IMREAD_GRAYSCALE)

# Save ROI for each age option at radius 20
centers = {'1':(418,202),'2':(417,247),'3':(418,299),
           '4':(418,348),'5':(698,195),'6':(696,247),
           '7':(698,299),'8':(698,348)}

for val, (cx, cy) in centers.items():
    roi = img[cy-20:cy+20, cx-20:cx+20]
    cv2.imwrite(f'debug_age_{val}.jpg', roi)

print('Saved debug_age_1 through debug_age_8')
