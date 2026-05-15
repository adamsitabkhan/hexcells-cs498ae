import os
import glob
import math
import matplotlib.pyplot as plt
from matplotlib.patches import RegularPolygon
from ..lib.parser import parse_hexcells, Problem, CellType, Color, Modifier, Orientation

def axial_to_pixel(q, r, size=1.0):
    # Hexcells uses flat-top hexagons. The text grid maps (i, j) -> q=j, r=(i-j)/2,
    # so straight-up neighbors share a column (i.e. flat-top stacking).
    x = size * 1.5 * q
    y = size * (math.sqrt(3.0) / 2.0) * (q + 2.0 * r)
    return x, y




def visualize_level(level_path: str, output_path: str):
    try:
        level = parse_hexcells(level_path)
        problem = Problem(level)
    except Exception as e:
        print(f"Failed to parse {level_path}: {e}")
        return

    fig, ax = plt.subplots(figsize=(12, 12))
    ax.set_aspect('equal')
    
    # Store coordinates for calculating bounding box
    all_x = []
    all_y = []
    
    # Draw cells
    for coords, cell in problem.cells.items():
        x, y = axial_to_pixel(coords.q, coords.r)
        
        # Determine color
        facecolor = '#FFD700' # Default Yellow
        if cell.color == Color.BLUE or cell.type == CellType.ZONE18:
            facecolor = '#4169E1' # Royal Blue
        elif cell.color == Color.BLACK or cell.type == CellType.ZONE6:
            facecolor = '#2F4F4F' # Dark Slate Gray
            
        edgecolor = '#B8860B' if facecolor == '#FFD700' else 'black'
            
        # orientation=0: first vertex at 0° (right), so top (90°) is an edge → flat-top
        hexagon = RegularPolygon((x, -y), numVertices=6, radius=0.95, orientation=math.pi/6,
                                 facecolor=facecolor, edgecolor=edgecolor, linewidth=1.5)
        ax.add_patch(hexagon)


        
        all_x.append(x)
        all_y.append(-y) # Invert Y so it draws top-to-bottom

    # Draw hints
    for hint in problem.hints:
        x, y = axial_to_pixel(hint.coords.q, hint.coords.r)
        
        text = str(hint.value)
        if hint.modifier == Modifier.TOGETHER:
            text = f"{{{text}}}"
        elif hint.modifier == Modifier.SEPARATED:
            text = f"-{text}-"
            
        if hint.type in (CellType.ZONE6, CellType.ZONE18):
            # Text inside the hexagon
            color = 'white'
            ax.text(x, -y, text, ha='center', va='center', color=color, fontweight='bold', fontsize=12)
        elif hint.type == CellType.LINE:
            # Line hints are drawn at their coordinate
            ax.text(x, -y, text, ha='center', va='center', color='black', fontweight='bold', fontsize=10, 
                    bbox=dict(facecolor='white', edgecolor='black', boxstyle='round,pad=0.2', alpha=0.8), zorder=10)
            all_x.append(x)
            all_y.append(-y)
            
            # Draw a semi-transparent line spanning the constraint's scope
            if hint.scope:
                # Find the furthest cell in the scope to draw the line
                # Since the scope is generated in order starting from the hint, the last element is the furthest.
                last_coord = hint.scope[-1]
                end_x, end_y = axial_to_pixel(last_coord.q, last_coord.r)
                ax.plot([x, end_x], [-y, -end_y], color='white', alpha=0.4, linewidth=6, zorder=1)


    if not all_x:
        print(f"No active cells found in {level_path}")
        plt.close(fig)
        return

    # Add global hint to the title
    ax.set_title(f"{os.path.basename(level_path)}\nTotal Mines: {problem.total_mines}", fontsize=14)

    # Set limits with some padding
    padding = 2.0
    ax.set_xlim(min(all_x) - padding, max(all_x) + padding)
    ax.set_ylim(min(all_y) - padding, max(all_y) + padding)
    ax.axis('off')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)

def main():
    inventory_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'levels')
    hexcells_files = glob.glob(os.path.join(inventory_dir, '*.hexcells'))
    
    print(f"Found {len(hexcells_files)} level files. Generating visualizations...")
    
    for i, file_path in enumerate(hexcells_files):
        output_path = file_path.replace('.hexcells', '.png')
        visualize_level(file_path, output_path)
        if (i + 1) % 20 == 0:
            print(f"Processed {i + 1}/{len(hexcells_files)}...")

        
    print("Done!")

if __name__ == '__main__':
    main()
