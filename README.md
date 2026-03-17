# Atlas Chat

## Overview

Cell types in online single-cell atlases are typically annotated with short and sometimes obscure names. Understanding what these names mean — and what is known about the cell types they describe — requires looking up the atlas paper and following its citations. While this scholarly workflow remains essential, it creates a significant barrier to efficient and effective browsing of online atlases.

Atlas Chat addresses this problem by enabling researchers to explore the literature associated with online atlases directly, without leaving their browsing context.

## What It Does

Atlas Chat supports two complementary workflows:

1. **Chat across the literature** — Ask questions spanning the primary atlas reference paper and any papers it cites. Get answers grounded in the source material rather than general model knowledge.

2. **Cell type reports** — Generate structured reports for individual cell types, drawn from the atlas paper and its cited literature. Reports include supporting quotes from source papers, allowing users to assess accuracy and rapidly navigate to relevant content.

## Design Principles

- **Source transparency** — Every claim in a generated report is backed by a direct quote from a source paper, so users can judge the evidence for themselves.
- **Literature navigation** — Quotes are linked to their source papers, enabling users to move quickly from a summary to the primary literature.
- **Complement, not replace** — Atlas Chat is designed to lower the barrier to efficient browsing, not to substitute for careful scholarly reading of the original papers.

## Status

Early development. See [main.py](main.py) for the current entry point.

## Dependencies and Integrations

Atlas Chat is built on:

- **[ARTL MCP](https://github.com/vrothenbergUSD/artl-mcp)** — tools for fetching and processing full-text papers
- **[Semantic Scholar (Asta)](https://www.semanticscholar.org/)** — academic paper search and metadata
- **Playwright** — browser automation for accessing online atlas interfaces
