from openai import OpenAI

client = OpenAI()

messages = [
    {"role": "system", "content": "Your primary goal is to help the user identify potential triggers..."},
    {"role": "user", "content": "Hey, I wanted to check in on how I'm feeling."}
]

while True:
    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages 
    )

    response_message = completion.choices[0].message
    messages.append({"role": "system", "content": response_message})
    print('---',response_message)
    
    user_input = input("You: ")
    if user_input.lower() == "exit":
        break

    messages.append({"role": "user", "content": user_input})
    print('###',messages)