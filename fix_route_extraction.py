#!/usr/bin/env python3
"""
Fix the route extraction to include function bodies.
This script properly extracts complete route functions from claims.py
"""

import re
from pathlib import Path
from typing import List

def find_function_body_end(lines: List[str], func_start_idx: int) -> int:
    """Find where a function ends by tracking indentation."""
    # Find the 'def' line
    def_idx = func_start_idx
    while def_idx < len(lines):
        if lines[def_idx].strip().startswith(('def ', 'async def ')):
            break
        def_idx += 1
    
    if def_idx >= len(lines):
        return func_start_idx
    
    # Get base indentation of function
    func_line = lines[def_idx]
    func_indent = len(func_line) - len(func_line.lstrip())
    
    # Scan forward to find end
    i = def_idx + 1
    while i < len(lines):
        line = lines[i]
        
        # Empty or comment lines don't count
        if not line.strip() or line.strip().startswith('#'):
            i += 1
            continue
        
        # Check indentation
        curr_indent = len(line) - len(line.lstrip())
        
        # If we're back at function indent or less, we've found the end
        if curr_indent <= func_indent:
            # Back up past any trailing blank lines
            end = i - 1
            while end > def_idx and not lines[end].strip():
                end -= 1
            return end
        
        i += 1
    
    # Reached end of file
    return len(lines) - 1

def extract_full_route(lines: List[str], route_decorator_idx: int) -> tuple[int, int, str]:
    """Extract a complete route including all decorators and function body."""
    # Find the start of decorators (may be multiple)
    start = route_decorator_idx
    while start > 0:
        prev_line = lines[start - 1].strip()
        if prev_line.startswith('@') or not prev_line:
            if prev_line.startswith('@'):
                start -= 1
            else:
                # Empty line - check one more back
                if start > 1 and lines[start - 2].strip().startswith('@'):
                    start -= 2
                else:
                    break
        else:
            break
    
    # Find function name and body end
    func_idx = route_decorator_idx
    while func_idx < len(lines) and not (lines[func_idx].strip().startswith('def ') or lines[func_idx].strip().startswith('async def ')):
        func_idx += 1
    
    if func_idx >= len(lines):
        return start, route_decorator_idx, ""
    
    func_match = re.search(r'(?:async\s+)?def\s+(\w+)', lines[func_idx])
    if not func_match:
        return start, route_decorator_idx, ""
    
    func_name = func_match.group(1)
    end = find_function_body_end(lines, route_decorator_idx)
    
    code = '\n'.join(lines[start:end + 1])
    return start, end, code

def test_extraction():
    """Test the extraction on claims.py"""
    claims_file = Path("src/claim_agent/api/routes/claims.py")
    content = claims_file.read_text()
    lines = content.split('\n')
    
    # Find first few routes
    test_count = 3
    routes_found = 0
    
    for i, line in enumerate(lines):
        if line.strip().startswith('@router.') and routes_found < test_count:
            start, end, code = extract_full_route(lines, i)
            print(f"Route {routes_found + 1}:")
            print(f"  Lines {start + 1} to {end + 1} ({end - start + 1} lines)")
            print(f"  First line: {lines[start][:60]}")
            print(f"  Last line: {lines[end][:60]}")
            print(f"  Code length: {len(code)} chars")
            print()
            routes_found += 1
    
    print(f"Tested extraction of {routes_found} routes")

if __name__ == "__main__":
    test_extraction()
