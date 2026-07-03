import sys

def fix_indentation(path):
    with open(path, 'r') as f:
        lines = f.readlines()
    
    # We want to find the api_ending_search function and fix the Tikhonov block
    # Actually, a simpler way is to just look for the double-indented lines and fix them.
    
    new_lines = []
    for line in lines:
        # If line has 20 spaces followed by 'for word in words_to_decompose:', it should probably be 16
        if line.startswith(' ' * 20 + 'for word in words_to_decompose:'):
            new_lines.append(' ' * 16 + 'for word in words_to_decompose:\n')
        # If line starts with 24 spaces and is after that for loop, it should be 20
        elif line.startswith(' ' * 24) and len(new_lines) > 0 and 'for word in words_to_decompose:' in "".join(new_lines[-50:]):
            new_lines.append(' ' * 20 + line[24:])
        else:
            new_lines.append(line)
            
    with open(path, 'w') as f:
        f.writelines(new_lines)

if __name__ == "__main__":
    fix_indentation(sys.argv[1])
