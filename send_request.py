# /// script
# dependencies = [
#   "requests"
# ]
# ///

import requests

payload={
  "email": "23f2004661@ds.study.iitm.ac.in",
  "secret": "toothless",
  "url": "https://tds-llm-analysis.s-anand.net/demo-audio?email=23f2004661%40ds.study.iitm.ac.in&id=15687"
}

r = requests.post("http://localhost:8000/task",json=payload)

print(r.json())
