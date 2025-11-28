# /// script
# dependencies = [
#   "requests"
# ]
# ///

import requests

payload={
  "email": "23f2004661@ds.study.iitm.ac.in",
  "secret": "toothless",
  "url": "https://tds-llm-analysis.s-anand.net/demo"
}

r = requests.post("http://localhost:8000/task",json=payload)

print(r.json())
# https://tds-llm-analysis.s-anand.net/demo-scrape?email=23f2004661%40ds.study.iitm.ac.in&id=21516
# https://tds-llm-analysis.s-anand.net/demo-audio?email=23f2004661%40ds.study.iitm.ac.in&id=16884