import os
import sys
import fitz
from openpyxl import Workbook


# Extract every internal link found in a PDF and collect metadata needed for the report.
def extract_links(pdf_path):
    """Return a list of internal links for a single PDF."""
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError("PDF file was not found: {0}".format(pdf_path))

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        raise ValueError("Unable to open PDF: {0}. Error: {1}".format(pdf_path, exc))

    all_links = []
    try:
        for page_index in range(document.page_count):
            page = document[page_index]
            page_links = page.get_links()
            for link in page_links:
                if not isinstance(link, dict):
                    continue

                kind = link.get("kind")
                if kind == fitz.LINK_URI:
                    continue

                all_links.append({
                    "PDF Name": os.path.basename(pdf_path),
                    "Page Number": page_index + 1,
                    "Link Kind": kind,
                    "Link Data": link,
                })
    finally:
        document.close()

    return all_links


# Validate whether a link resolves to a valid destination inside the same PDF.
def _is_valid_internal_target(document, link):
    """Return True when an internal link resolves to an actual page or named destination."""
    if not isinstance(link, dict):
        return False

    kind = link.get("kind")

    # External links are intentionally ignored by this prototype.
    if kind == fitz.LINK_URI:
        return True

    # For page-to-page jumps, the destination page must exist in the document.
    if kind == fitz.LINK_GOTO:
        target_page = link.get("page")
        if target_page is None:
            target_page = link.get("to")
        if target_page is None:
            return False

        try:
            target_page = int(target_page)
        except (TypeError, ValueError):
            return False

        return 0 <= target_page < document.page_count

    # Named destinations must resolve and point to a real page in the PDF.
    if kind == fitz.LINK_NAMED:
        name = link.get("name")
        if not name:
            return False

        try:
            if hasattr(document, "resolve_link"):
                resolved = document.resolve_link(link)
                if resolved is None:
                    return False
                if isinstance(resolved, dict):
                    page_number = resolved.get("page")
                    if page_number is None:
                        page_number = resolved.get("to")
                    if page_number is not None:
                        try:
                            page_number = int(page_number)
                        except (TypeError, ValueError):
                            return False
                        return 0 <= page_number < document.page_count
                if isinstance(resolved, (list, tuple)) and resolved:
                    first_value = resolved[0]
                    try:
                        first_value = int(first_value)
                    except (TypeError, ValueError):
                        return False
                    return 0 <= first_value < document.page_count
        except Exception:
            pass

        try:
            if hasattr(document, "get_named_dest"):
                named_destinations = document.get_named_dest()
                if isinstance(named_destinations, dict):
                    destination = named_destinations.get(name)
                    if destination is None:
                        return False
                    if isinstance(destination, dict):
                        page_number = destination.get("page")
                        if page_number is None:
                            page_number = destination.get("pageno")
                        if page_number is not None:
                            try:
                                page_number = int(page_number)
                            except (TypeError, ValueError):
                                return False
                            return 0 <= page_number < document.page_count
                    if isinstance(destination, (list, tuple)) and destination:
                        first_value = destination[0]
                        try:
                            first_value = int(first_value)
                        except (TypeError, ValueError):
                            return False
                        return 0 <= first_value < document.page_count
        except Exception:
            pass

        return False

    return True


# Detect the subset of links that are broken for one PDF.
def detect_broken_links(pdf_path):
    """Return only the broken internal links from the supplied PDF."""
    links = extract_links(pdf_path)
    if not links:
        return []

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        raise ValueError("Unable to open PDF for validation: {0}. Error: {1}".format(pdf_path, exc))

    broken = []
    try:
        for link_record in links:
            link = link_record["Link Data"]
            kind = link.get("kind")
            if kind in (fitz.LINK_GOTO, fitz.LINK_NAMED):
                if not _is_valid_internal_target(document, link):
                    broken.append({
                        "PDF Name": link_record["PDF Name"],
                        "Page Number": link_record["Page Number"],
                        "Discrepancy": "Yes",
                    })
    finally:
        document.close()

    return broken


# Create the Excel report workbook using the required columns.
def generate_excel_report(results, output_path):
    """Write all broken-link results to an Excel workbook."""
    output_directory = os.path.dirname(output_path)
    if output_directory and not os.path.exists(output_directory):
        os.makedirs(output_directory)

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Broken Links"
    worksheet.append(["PDF Name", "Page Number", "Discrepancy"])

    for result in results:
        worksheet.append([
            result.get("PDF Name", ""),
            result.get("Page Number", ""),
            result.get("Discrepancy", "No"),
        ])

    workbook.save(output_path)
    return output_path


# Combine results across multiple PDFs and pass them to the report generator.
def main():
    """Accept a PDF file or folder and generate a broken-link Excel report."""
    if len(sys.argv) != 2:
        print("Usage: python detect_broken_links.py <path_to_pdf_or_folder>", file=sys.stderr)
        return 1

    input_path = sys.argv[1]
    if not os.path.exists(input_path):
        print("Error: The provided path does not exist: {0}".format(input_path), file=sys.stderr)
        return 1

    script_directory = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_directory, "broken_links_report.xlsx")

    if os.path.isfile(input_path):
        if not input_path.lower().endswith(".pdf"):
            print("Error: Please provide a PDF file or a folder containing PDFs.", file=sys.stderr)
            return 1
        pdf_files = [input_path]
    else:
        pdf_files = []
        for root, _, files in os.walk(input_path):
            for file_name in files:
                if file_name.lower().endswith(".pdf"):
                    pdf_files.append(os.path.join(root, file_name))

    if not pdf_files:
        print("No PDF files were found in the provided path.", file=sys.stderr)
        return 1

    all_broken_links = []
    for pdf_file in pdf_files:
        try:
            broken = detect_broken_links(pdf_file)
            all_broken_links.extend(broken)
        except Exception as exc:
            print("Warning: Skipping {0}. Reason: {1}".format(pdf_file, exc), file=sys.stderr)

    generate_excel_report(all_broken_links, output_path)

    if all_broken_links:
        print("Broken links found. Report saved to: {0}".format(output_path))
    else:
        print("No broken internal links were found. Report saved to: {0}".format(output_path))

    return 0


if __name__ == "__main__":
    sys.exit(main())
