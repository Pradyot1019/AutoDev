# Live-Model Evaluation Plan

This document outlines the steps to reproduce Tables VIII, IX and X, which measure end-to-end performance of the AutoDev system with real LLMs.

## Requirements

Reproducing these tables requires:

1. API keys for the LLM providers being evaluated (Google, OpenAI, Groq, etc)
2. A machine or environment that allows API calls to those providers 
3. Sufficient compute resources to handle the cost of the LLM calls

## Options

There are a few ways to run this evaluation:

1. **Local machine**: Run the repo's `eval/live_eval.py` script on a local machine configured with your API keys. This is the simplest option but incurs cost on your personal keys, so monitor spend closely.

2. **Hosted runner**: Deploy the evaluation suite to a cloud compute platform like Google Colab, Cocalc or AWS. Pass your API keys securely. Benefits are isolated spend and burst compute, but it requires some setup.

3. **University resources**: Check if BMSCE provides any LLM-enabled compute that can be scheduled for larger experiments. This could provide free, isolated compute but may have a lead time.

## Cost Considerations

A full run matching the original experiment's sample size will cost ₹7,000 - ₹10,000. To control spend:

- Start with a small sample (1-2 services, 10-20 prompts) 
- Set a tight budget limit
- Control model sizes and output lengths via `model_kwargs`

## Scoping for Review

For conference or workshop submission, include:

- A smaller-scale test with real LLM calls to validate end-to-end flow
- Implementation details (API keys, etc) in Supplemental Materials
- Clear "Methods" section detailing dataset sizes, models used, and any extrapolation 

For your project advisor, provide:

- Maximum subset of Tables VIII-X that you can afford to run
- Methodology documentation (dataset, models, extrapolation approach)

Ping me for any other brainstorming help needed on scoping this evaluation within practical constraints. The key is demonstrating real LLM-powered flow in a tractable way.