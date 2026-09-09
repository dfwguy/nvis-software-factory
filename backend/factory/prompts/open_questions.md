---
revision: 1
description: Ask the questions whose answers would change the assessment, so ambiguity is surfaced rather than guessed.
---

## SYSTEM

Static evidence cannot answer everything about a piece of software, and the honest response to that
is a question rather than an assumption. This pass produces the questions.

A good question here has one property: **the answer changes something**. If both answers lead to
the same recommendation, the question is noise and you should drop it.

Rank by how much the answer moves the assessment. The three that usually matter most, if the
evidence has not settled them:

- **Who depends on this?** One person's scratch tool and a service three teams import have
  different durability requirements for identical code. This single answer can move half the
  findings a full severity level.
- **What is the cost of losing the data?** "Re-run it in ten minutes" and "a week of a customer
  bring-up" are different problems wearing the same code.
- **Is this a prototype or is it in service?** A prototype is allowed to be a prototype. What is
  not allowed is a prototype that quietly became infrastructure.

Address the questions to the repository's author, in second person. They will read this as a
document, so make each one answerable in a sentence — a question that needs an essay does not get
answered.

Reply with a JSON object only.

## USER

Repository: {repository}

Architecture:
{architecture}

What earlier passes could not determine:
{undetermined}

Open questions raised while judging the pillars:
{pillar_questions}

Return this JSON object:

{{
  "questions": [
    {{
      "question": "second person, answerable in a sentence",
      "why_it_matters": "what changes in the assessment depending on the answer",
      "if_yes": "what we would recommend",
      "if_no": "what we would recommend instead",
      "affects": ["pillar ids this answer changes"]
    }}
  ],
  "assumptions_made": [
    {{
      "assumption": "what the assessment assumed in the absence of an answer",
      "chosen_because": "why this was the safe direction to assume",
      "if_wrong": "which findings become wrong if this assumption is wrong"
    }}
  ]
}}
