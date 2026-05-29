“Vibe-Cloning” — Engineering Assessment
Why we're doing this
As an early-stage startup, we frequently go zero-to-one on new features and products. We need to be able to take a fuzzy idea, scope a useful MVP, make deliberate tradeoffs, and ship something that demonstrates value quickly.

This assessment is designed to test this skillset. You have 3-4 hours to complete it independently.
The Task: Build an MVP
The real product is an AI agent that places outbound phone calls to insurance payers on behalf of a medical provider to check the status of submitted claims. It speaks with a human (or IVR) on the other end, navigates the call, asks the right questions, captures the answers, and writes structured results back for the provider's billing team.

For each claim, the data that the voice agent will have should match an 837 EDI file. On the call, the payer agent will ask for the provider NPI, the patient member ID, the tax ID, the patient's name and date of birth, and the date of service. Then once you have been verified, you can ask for the claim status details. The response you get back should match what you would receive in an 835 EDI file. You should ensure that you ask for the complete details, along with the rep's name and reference number, at the end of the call.

On the call itself, we should ask for statuses for as many claims as the rep allows, up to 3. 

The goal is to independently build a functional MVP version of this voice agent.

To the best of your ability, it should:

Capture the core value the real product delivers (extracting structured claim status data from a conversation).
Be runnable end-to-end — we should be able to run it locally and interact with it.
Reflect deliberate tradeoffs about system design, scope, and error handling given the 3-hour limit.

You should use AI tools (claude code, cursor, conductor, etc.) as necessary. We care about what you choose to build, what you choose to cut, and how you reason about both. The code is not expected to be perfect.


Note that there is intentionally ambiguity in this objective, and you are highly encouraged to ask questions that you deem relevant. Part of the goal here is for you to think through what kinds of questions you would ask customers to make sure we are building the right thing. 

Things to think about:
How do we set this up in a way that's extensible? We know that soon we will have to enable our system to be able to call for other objectives (e.g we have received a denial electronically but it is ambiguous, so we must make a phone call to clarify some aspect of it) and would like to be able to enable this seamlessly. 
What testing can we do upfront, what we would want to monitor when we start making the calls if this was a real product, and how we would think about improving upon the things we encounter in production?
What evals should we have for different parts of the pipeline? As new open/closed models are released, how do we know if/how we can use them to improve our offering?

Deliverables
At the end of the 3 hours, please submit:

Code: Your working implementation.
Decision Log (Markdown file): A short document (1 page max, bullet points are fine) covering:
Scoping Assumptions: What assumptions did you make about the product requirements or user needs to narrow the scope?
Key Decisions: The 3–5 most interesting technical decisions you made — what you chose, what you didn't, and why.
Next Steps: What would you do next if you had another week?

