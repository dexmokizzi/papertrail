"""
Test moondream vision model on a real survey page.
"""
import base64
import json
import requests

image_path = "data/processed/CamScanner 4-24-26 22.42_page01.jpg"
with open(image_path, "rb") as f:
    image_b64 = base64.b64encode(f.read()).decode("utf-8")

prompt = """This is a survey form with 10 questions.
Each row has a question number on the left and four answer
options labeled 1, 2, 3, 4 across the top.
The respondent has circled or marked one number in each row.

Look carefully at each row and identify which number
(1, 2, 3, or 4) has been circled or marked.

Return ONLY a JSON object with no explanation, like this:
{"Q1": 4, "Q2": 3, "Q3": 2, "Q4": 1, "Q5": 3,
 "Q6": 4, "Q7": 1, "Q8": 2, "Q9": 3, "Q10": 4}"""

print("Sending request to moondream...")
print("This may take 1-3 minutes on CPU...")

try:
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model":  "moondream",
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
        },
        timeout=300,
    )

    print(f"Status: {response.status_code}")
    result = response.json()

    if "error" in result:
        print(f"Model error: {result['error']}")
    else:
        raw = result.get("response", "")
        print(f"\nRaw response:\n{raw}")

        # Try to parse JSON
        try:
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start >= 0 and end > start:
                detected = json.loads(raw[start:end])
                known = {
                    "Q1":4,"Q2":3,"Q3":2,"Q4":3,"Q5":3,
                    "Q6":3,"Q7":1,"Q8":1,"Q9":2,"Q10":4
                }
                correct = 0
                print("\nDetected vs expected:")
                for q, expected in known.items():
                    got = detected.get(q, "?")
                    ok  = "✅" if str(got) == str(expected) else "❌"
                    print(f"  {q}: got={got}  expected={expected}  {ok}")
                    if str(got) == str(expected):
                        correct += 1
                print(f"\n{correct}/10 correct")
        except Exception as e:
            print(f"Could not parse JSON: {e}")

except requests.exceptions.Timeout:
    print("Timed out after 5 minutes — model too slow on CPU")
except Exception as e:
    print(f"Request error: {e}")
