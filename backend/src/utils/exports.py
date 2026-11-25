import csv
import io


def _safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
        return "'" + value
    return value


def write_csv(rows, fields=None, spreadsheet_safe=True):
    stream = io.StringIO(newline='')
    fields = fields or (list(rows[0]) if rows else ['结果'])
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _safe_cell(value) if spreadsheet_safe else value for key, value in row.items()})
    return stream.getvalue().encode('utf-8-sig')
