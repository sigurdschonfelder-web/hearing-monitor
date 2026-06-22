# Hearing Monitoring Prototype

## Overview

This project is a proof-of-concept (PoC) for automatically monitoring parliamentary hearings, identifying new hearings, retrieving hearing content, and assessing relevance for Spekter using a Retrieval-Augmented Generation (RAG) pipeline and a Large Language Model (LLM).

The system combines hearing data from multiple sources, retrieves relevant historical hearing responses, and generates a structured assessment with recommendations.

<img width="784" height="690" alt="image" src="https://github.com/user-attachments/assets/925ad813-7943-4451-88be-18c824536182" />


## Project Structure

```text
.
├── proto.py          # Main application logic and workflow
├── helper.py         # Utility and helper functions
├── rag.py            # RAG retrieval logic and vector search
├── data/             # JSON, TXT, and other data files
└── README.md
```

### Files

* **proto.py**

  * Entry point of the application.
  * Fetches hearings, identifies new hearings, retrieves content, performs RAG retrieval, calls the LLM, and stores results.

* **helper.py**

  * Contains helper functions used throughout the project.
  * Includes data loading, storage, scraping, API integration, and utility functions.

* **rag.py**

  * Handles Retrieval-Augmented Generation (RAG).
  * Retrieves relevant historical hearing responses to provide context for the LLM.

* **data/**

  * Contains JSON and TXT files used by the application.
  * Includes hearing metadata, known hearing IDs, historical hearing responses, and generated outputs.

## Usage

Run the main application:

```bash
python proto.py
```

## Notes

This project was developed as a proof-of-concept and is not production-ready. Operational deployment would require:

* Dedicated API keys and credential management
* Automated scheduled execution
* Logging and monitoring
* Error handling and operational maintenance
* Deployment within Spekter's or Intility's infrastructure
