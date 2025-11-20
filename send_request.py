# /// script
# dependencies = [
#   "requests"
# ]
# ///

import requests


payload = {
  "email": "23f2004661@ds.study.iitm.ac.in", 
  "secret": "toothless", 
  "url": "https://example.com/quiz-834" 
}

r = requests.post("http://localhost:8000/task",json=payload)

print(r.json())
