# /// script
# dependencies = [
#   "requests"
# ]
# ///

import requests

payload={
  "email": "23f2004661@ds.study.iitm.ac.in",
  "secret": "toothless",
  "url": "https://tds-llm-analysis.s-anand.net/project2"
}

r = requests.post("http://localhost:8000/task",json=payload)

print(r.json())

# https://tds-llm-analysis.s-anand.net/demo
# https://tds-llm-analysis.s-anand.net/demo-scrape?email=23f2004661%40ds.study.iitm.ac.in&id=21516
# https://tds-llm-analysis.s-anand.net/demo-audio?email=23f2004661%40ds.study.iitm.ac.in&id=16884
# https://p2testingone.vercel.app/q1.html
# https://tdsbasictest.vercel.app/quiz/1

#https://tds-llm-analysis.s-anand.net/project2-audio-passphrase?email=23f2004661%40ds.study.iitm.ac.in&id=62645
# https://tds-llm-analysis.s-anand.net/project2