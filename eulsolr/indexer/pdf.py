# not sure where this code should ultimately belong...
# putting it here until we decide

from pyPdf import PdfFileReader

def pdf_to_text(pdfstream):
    '''Extract the text from a PDF document, e.g. to add PDF text
    content to an index for searching.

    :param pdfstream: A file-like object that supports read and seek
	    methods, as required by :class:`pyPdf.PdfFileReader` 

    '''
    pdfreader = PdfFileReader(pdfstream)
    if pdfreader.isEncrypted:
        raise Exception('Cannot extract text from encrypted PDF documents')
    return '\n'.join([page.extractText() for page in pdfreader.pages])

    
