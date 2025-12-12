# Task to run at the Background (Solve Quiz)
def solve_quiz(data):
  # This is just a dummy prompt
  prompt = f"""
You are an autonomous Python agent.
Your job is to generate a complete stand-alone Python script called solving_quiz.py.
This script will be executed by me exactly as you produce it — so it must run with zero modifications.

REQUIREMENT: At the TOP of your output, you MUST include an inline metadata block using this exact format:

# /// script
# dependencies = [
#    "dependency1",
#    "dependency2",
#    ...
# ]
# ///

IMPORTANT RULES ABOUT THE METADATA BLOCK:
- DO NOT include "playwright" in the dependency list — I already have it installed.
- Include ONLY the libraries your generated script needs (pandas, PyPDF2, pillow, requests, etc.).
- The dependency list MUST change dynamically depending on the code you generate.
- After this metadata block, output ONLY valid Python code.
- No backticks. No markdown. No explanations. No comments outside the code.

------------------------------------------------------------
INPUT PAYLOAD
------------------------------------------------------------

Use the following JSON payload:

{data}

This contains:
- email
- secret
- url  (quiz URL)
- possibly other fields

Your script must use this data.

------------------------------------------------------------
WHAT YOUR GENERATED PYTHON SCRIPT MUST DO
------------------------------------------------------------

1. USE PLAYWRIGHT (Python) to open the given quiz URL
   - Use Chromium in headless mode.
   - Wait until all JavaScript is fully rendered.
   - Extract all visible text and HTML.
   - Extract:
       - the question
       - instructions
       - submit URL
       - any download links
       - any tables rendered on the page
       - any embedded JSON or code snippets.

2. UNDERSTAND THE QUIZ DYNAMICALLY
   The quiz may ask for:
   - numeric answers
   - strings
   - booleans
   - JSON objects
   - downloading and processing CSV, JSON, images, text, or PDF files
   - computing aggregates, sums, stats, parsing tables, etc.
   - base64 encoding file attachments

   Your script must:
   - analyze the instructions extracted from the page
   - interpret the required task
   - download and parse any required files
   - use Python libraries (pandas, csv, json, pillow, PyPDF2, etc.)
   - produce the correct final answer

3. COMPUTE THE ANSWER
   - Must match the exact required format mentioned on the quiz page.
   - Ensure JSON payload < 1MB.
   - Answer may be:
        number, string, boolean,
        nested JSON,
        base64-encoded file attachment.

4. SUBMIT THE ANSWER
   - The page always contains the correct submission endpoint.
   - POST this JSON:
       {{
           "email": data["email"],
           "secret": data["secret"],
           "url": data["url"],
           "answer": COMPUTED_ANSWER
       }}
   - Print status code + response JSON.

5. ERROR HANDLING
   - Must catch ALL exceptions
   - Must print readable debug information
   - Script must not silently crash

6. SCRIPT FORMAT RULES
   - The output must begin with the metadata block
   - Then valid Python code only
   - No markdown formatting
   - No explanations
   - The script must include:
       all imports
       Playwright async logic
       file download helpers
       parsing helpers
       compute logic
       submit logic
       a main() function
       if __name__ == "__main__": main()

------------------------------------------------------------

NOW PRODUCE THE COMPLETE SCRIPT.

Your output MUST contain:
1. The inline metadata block
2. Only Python code afterwards
3. No comments outside Python
4. No backticks

Generate solving_quiz.py now.

"""
  try:
    print("Task has Started")
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=prompt,
      # config=types.GenerateContentConfig(
      #     tools=[types.Tool(code_execution=types.ToolCodeExecution)]
      # ),
    )

    print("✅ Got the response from the LLM")
    print(response)
    part = response.candidates[0].content.parts[0]
    script_text = part.text   
    with open("solving_quiz.py", "w") as f:
      f.write(script_text)
    print("✅ Written the solving_quiz.py file")

  except Exception as e:
    print("❌ Failed to get the response from the LLM")
    print("Error:", str(e))
    traceback.print_exc()
  finally:
    client.close()
