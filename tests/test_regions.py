import cv2
import yaml
import numpy as np

# Load image in color so we can draw colored boxes
image = cv2.imread(
    'data/processed/CamScanner 3-21-26 14.29.jpg'
)

with open('config/surveys/test_survey.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Draw all calibrated regions on the image
colors = {
    "1": (255, 0,   0),    # Blue
    "2": (0,   255, 0),    # Green
    "3": (0,   0,   255),  # Red
    "4": (255, 165, 0),    # Orange
}

for field in config['fields']:
    regions = field.get('regions', {})
    for value, region in regions.items():
        x, y, w, h = (region['x'], region['y'],
                      region['w'], region['h'])
        color = colors.get(str(value), (255, 255, 255))
        cv2.rectangle(image, (x, y), (x+w, y+h), color, 3)
        cv2.putText(
            image,
            f"{field['paper_id']}={value}",
            (x, y - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6, color, 2
        )

# Save the visualization
cv2.imwrite('data/processed/regions_debug.jpg', image)
print("Saved to data/processed/regions_debug.jpg")
print("Open that file to see where your calibration boxes are.")