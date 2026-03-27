#!/usr/bin/env python3
"""Script to extract route definitions and their line ranges from claims.py."""

import re
from pathlib import Path
from typing import List, Tuple

def find_route_ranges(content: str) -> List[Tuple[str, int, int]]:
    """Find all route functions with their start and estimated end lines."""
    lines = content.split('\n')
    routes = []
    current_route = None
    current_start = None
    indent_level = None
    
    for i, line in enumerate(lines, 1):
        # Check if this is a route decorator
        if line.strip().startswith('@router.'):
            if current_route and current_start:
                # Save previous route
                routes.append((current_route, current_start, i - 1))
            # Look ahead for the function name
            j = i
            while j < len(lines) and not lines[j].strip().startswith('def ') and not lines[j].strip().startswith('async def '):
                j += 1
            if j < len(lines):
                func_match = re.search(r'(?:async\s+)?def\s+(\w+)', lines[j])
                if func_match:
                    current_route = func_match.group(1)
                    current_start = i
                    indent_level = len(lines[j]) - len(lines[j].lstrip())
        
        # Check if current function ended (next def at same or lower indent, or next @router)
        elif current_route and line.strip() and not line.strip().startswith('#'):
            if line.startswith('def ') or line.startswith('async def ') or line.startswith('class ') or line.startswith('@router.'):
                curr_indent = len(line) - len(line.lstrip())
                if curr_indent == 0:  # Top level definition
                    routes.append((current_route, current_start, i - 1))
                    current_route = None
                    current_start = None
    
    # Don't forget the last route
    if current_route and current_start:
        routes.append((current_route, current_start, len(lines)))
    
    return routes

def main():
    claims_file = Path("src/claim_agent/api/routes/claims.py")
    content = claims_file.read_text()
    
    routes = find_route_ranges(content)
    
    print("Route ranges found:")
    print("=" * 80)
    for func_name, start, end in routes:
        print(f"{func_name:40} lines {start:5}-{end:5} ({end-start+1:4} lines)")
    
    print(f"\nTotal routes: {len(routes)}")
    print(f"Total lines in routes: {sum(end - start + 1 for _, start, end in routes)}")

if __name__ == "__main__":
    main()
