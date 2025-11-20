# /// script
# dependencies = [
#   "fastapi",
#   "uvicorn",
#   "dotenv",
#   "google-genai"
# ]
# ///

from fastapi import FastAPI, BackgroundTasks
import uvicorn
import os
import dotenv
from fastapi.middleware.cors import CORSMiddleware
from google import genai
dotenv.load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

""" This is what the request will look like 
{
  "email": "your email", // Student email ID
  "secret": "your secret", // Student-provided secret
  "url": "https://example.com/quiz-834" // A unique task URL
  // ... other fields
}
"""

# Task to run at the Background (Solve Quiz)
def solve_quiz(data):
  # This is just a dummy prompt
  prompt="""
  Strongest Dragon in How to Train your Dragon?.
  """
  try:
    print("Task has Started")
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=prompt,
    )
    print("✅ Got the response from the LLM")
    print(f"The response is:\n{response.text}")
    u = response.usage_metadata
    print(f"Total tokens used: {u.total_token_count}")
    # print(dir(response))
  except Exception as e:
    print("❌ Failed to get the response from the LLM")
  finally:
    client.close()


@app.post("/task")
def handle_task(data: dict, background_tasks: BackgroundTasks):
    secret=os.getenv("SECRET")
    print(data)
    if data.get("secret")  == secret:
        # Run the task in background (not implemented here)
        background_tasks.add_task(solve_quiz, data)
        return {"message": "Secret Matches!", "status_code": 200}
    else:
        return {"message":"Secret does not match", "status_code": 403}


if __name__ == "__main__":
  import uvicorn
  uvicorn.run(app,port=8000)
    


