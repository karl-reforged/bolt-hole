#!/bin/bash
# Refresh the Bolt Hole pipeline — re-scrapes all sources, re-scores, rebuilds shortlist
cd "$(dirname "$0")"
python3 search.py
python3 shortlist.py
echo "Done — shortlist updated at docs/index.html"
