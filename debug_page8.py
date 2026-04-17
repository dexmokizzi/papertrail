import cv2, numpy as np, sys
sys.path.insert(0, '.')
from src.scanner.omr import detect_mark

img = cv2.imread('data/processed/CamScanner 4-14-26 10.04_page08.jpg', cv2.IMREAD_GRAYSCALE)

fields = [
    ('S8_age_Q1', 'circled_bubble', {
        '1':(418,202),'2':(417,247),'3':(418,299),
        '4':(418,348),'5':(698,195),'6':(696,247),
        '7':(698,299),'8':(698,348)}),
    ('S8_gender_Q1', 'circled_bubble', {
        '1':(1095,168),'2':(1095,226),'3':(1097,273),
        '4':(1099,320),'5':(1097,429)}),
    ('S8_race_Q1', 'circled_bubble', {
        '1':(1093,1072),'2':(1093,1127),'3':(1095,1177),
        '4':(1095,1228),'5':(1097,1275),'6':(1091,1330)}),
]

for name, mark_type, centers in fields:
    config = {
        'mark_type': mark_type,
        'regions': {k: {'x':v[0],'y':v[1]} for k,v in centers.items()}
    }
    result = detect_mark(img, config)
    print(name, 'value:', result.get('value'), 'flag:', result.get('flag',''))
    print('  scores:', result.get('all_scores'))
