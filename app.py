import os
import re
import quopri
from flask import Flask, request, render_template, jsonify
from bs4 import BeautifulSoup

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024


def parse_mhtml(file_bytes, filename):
    """Parse resOS MHTML booking list and extract real reservation data."""
    base = os.path.splitext(filename)[0].replace('_', ' ')
    match = re.match(r'^(.+?)\s*-\s*resOS$', base, re.IGNORECASE)
    restaurant_name = match.group(1).strip() if match else base

    decoded = quopri.decodestring(file_bytes).decode('utf-8', errors='ignore')
    html_match = re.search(r'<!DOCTYPE html>.*', decoded, re.DOTALL)
    if not html_match:
        return restaurant_name, '', []

    soup = BeautifulSoup(html_match.group(0), 'html.parser')

    # Get the date shown in the page header
    date_input = soup.find('input', {'readonly': True})
    page_date = date_input['value'] if date_input else ''

    # Remove the activity drawer (sidebar) — it contains different data
    for drawer in soup.find_all('div', class_=re.compile('MuiDrawer')):
        drawer.decompose()

    # Parse the booking table rows
    rows = soup.find_all('tr', class_=re.compile('MuiTableRow'))
    bookings = []

    for row in rows[1:]:  # skip header row
        cells = row.find_all('td')
        if not cells:
            continue

        texts = [c.get_text(' ', strip=True) for c in cells]

        # Structure: ['', 'HH:MM HH:MM', 'Name cell', '', 'pax', 'table', '', 'Status']
        if len(texts) < 6:
            continue

        time_cell = texts[1]
        pax_cell  = texts[4]
        status    = texts[7] if len(texts) > 7 else texts[-1]

        # Extract start time only
        time_match = re.match(r'(\d{1,2}:\d{2})', time_cell)
        if not time_match:
            continue
        time_val = time_match.group(1)

        # Skip cancelled/no-show/deleted bookings
        if any(s in status.lower() for s in ['cancel', 'no-show', 'deleted']):
            continue

        # The name cell has two direct-child divs:
        #   [0] jss2339: guest name in format "roomNumber** guestName" or just "guestName"
        #   [1] jss2361: staff-only notes with a Note icon — ignore completely
        name_td = cells[2]
        direct_divs = name_td.find_all('div', recursive=False)
        raw = direct_divs[0].get_text(strip=True) if direct_divs else name_td.get_text(strip=True)

        # Format: "roomNumber** guestName" — digits/slashes, then one or more *, then name
        room = ''
        name = raw
        m = re.match(r'^([\d/]+)\*+\s*(.*)', raw)
        if m:
            room = m.group(1).strip()
            name = m.group(2).strip()

        # Strip trailing inline staff note after " *** " (e.g. "Mr. Larsen *** já tem ticket...")
        name = re.sub(r'\s+\*\*\*\s+.*$', '', name).strip()

        # Fallback: if name is empty after parsing, keep raw value
        if not name:
            name = raw

        if not pax_cell.isdigit():
            continue

        bookings.append({
            'name': name,
            'room': room,
            'date': page_date,
            'time': time_val,
            'pax': pax_cell,
        })

    return restaurant_name, page_date, bookings


def generate_tickets_html(restaurant_name, page_date, bookings):
    tickets = ''
    for b in bookings:
        tickets += f"""
        <div class="ticket">
          <div class="stripe"></div>
          <div class="ticket-inner">
            <div class="ticket-top">
              <div class="brand">
                <div class="brand-name">{restaurant_name.upper()}</div>
                <div class="brand-sub">Restaurant Reservation</div>
              </div>
              <div class="reservation-label">Reservation</div>
            </div>
            <div class="divider"></div>
            <div class="fields">
              <div class="field">
                <span class="field-label">Guest</span>
                <span class="field-value">{b['name']}</span>
              </div>
              <div class="field">
                <span class="field-label">Room</span>
                <span class="field-value field-room">{b['room']}</span>
              </div>
            </div>
            <div class="ticket-bottom">
              <div class="bottom-field">
                <span class="bottom-label">Date</span>
                <span class="bottom-value">{b['date']}</span>
              </div>
              <div class="bottom-field">
                <span class="bottom-label">Time</span>
                <span class="bottom-value">{b['time']}</span>
              </div>
              <div class="pax-badge">
                <span class="pax-num">{b['pax']}</span>
                <span class="pax-label">pax</span>
              </div>
            </div>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{restaurant_name} — {page_date}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: Arial, sans-serif; font-weight:700; background:#eee; }}

  .print-bar {{
    background: #111; color: white;
    padding: 10px 24px;
    display: flex; align-items: center; justify-content: space-between;
    font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;
    position: sticky; top: 0; z-index: 100;
  }}
  .print-bar span {{ opacity: 0.6; }}
  .print-btn {{
    background: white; color: #111; border: none;
    padding: 7px 18px; font-family: inherit; font-size: 10px;
    font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase;
    cursor: pointer; border-radius: 3px;
  }}
  .print-btn:hover {{ background: #ddd; }}

  .page {{
    width: 210mm; min-height: 297mm; background: white;
    margin: 20px auto; padding: 8mm;
    display: grid; grid-template-columns: 1fr 1fr;
    align-content: start; gap: 0;
    box-shadow: 0 4px 24px rgba(0,0,0,0.15);
  }}

  .ticket {{
    border: 0.5mm solid #111; border-radius: 0;
    overflow: hidden; display: flex;
    page-break-inside: avoid; break-inside: avoid;
    margin: -0.25mm;
  }}
  .stripe {{ width: 6mm; background: #111; flex-shrink: 0; }}
  .ticket-inner {{
    flex: 1; padding: 2.5mm 4mm;
    display: flex; flex-direction: column; gap: 1.5mm; color: #111;
  }}
  .ticket-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .brand-name {{ font-size: 14pt; font-weight: 700; letter-spacing: 0.08em; line-height: 1; }}
  .brand-sub {{ font-size: 5pt; letter-spacing: 0.2em; text-transform: uppercase; margin-top: 1mm; font-weight: 700; }}
  .reservation-label {{ font-size: 5pt; letter-spacing: 0.15em; text-transform: uppercase; font-weight: 700; }}
  .divider {{ height: 0.3mm; background: #111; }}
  .fields {{ display: flex; flex-direction: column; gap: 2mm; }}
  .field {{ display: flex; align-items: baseline; gap: 2mm; }}
  .field-label {{ font-size: 5pt; letter-spacing: 0.2em; text-transform: uppercase; min-width: 10mm; font-weight: 700; }}
  .field-value {{ font-size: 9.5pt; font-weight: 700; }}
  .field-room {{ display: inline-block; }}
  .ticket-bottom {{
    display: flex; justify-content: space-between; align-items: center;
    padding-top: 1.5mm; border-top: 0.3mm solid #ccc;
  }}
  .bottom-field {{ display: flex; flex-direction: column; gap: 0.4mm; }}
  .bottom-label {{ font-size: 4pt; letter-spacing: 0.2em; text-transform: uppercase; font-weight: 700; }}
  .bottom-value {{ font-size: 9pt; font-weight: 700; }}
  .pax-badge {{
    background: #111; color: white; width: 8mm; height: 8mm;
    border-radius: 50%; display: flex; align-items: center;
    justify-content: center; flex-direction: column; line-height: 1;
  }}
  .pax-num {{ font-size: 8.5pt; font-weight: 700; }}
  .pax-label {{ font-size: 3pt; letter-spacing: 0.05em; text-transform: uppercase; font-weight: 700; }}

  @media print {{
    .print-bar {{ display: none; }}
    body {{ background: white; }}
    .page {{ margin: 0; box-shadow: none; width: 100%; padding: 8mm; }}
  }}
</style>
</head>
<body>
<div class="print-bar">
  <span>{restaurant_name} &mdash; {page_date} &mdash; {len(bookings)} reservations</span>
  <button class="print-btn" onclick="window.print()">🖨 Print</button>
</div>
<div class="page">
{tickets}
</div>
</body>
</html>"""


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'No file selected'}), 400

    try:
        restaurant_name, page_date, bookings = parse_mhtml(f.read(), f.filename)
    except Exception as e:
        return jsonify({'error': f'Failed to parse file: {str(e)}'}), 400

    if not bookings:
        return jsonify({'error': 'No reservations found. Make sure this is a valid resOS booking list saved as .mhtml.'}), 400

    html = generate_tickets_html(restaurant_name, page_date, bookings)
    return jsonify({'html': html, 'count': len(bookings), 'restaurant': restaurant_name})


if __name__ == '__main__':
    app.run(debug=True, port=5050)
