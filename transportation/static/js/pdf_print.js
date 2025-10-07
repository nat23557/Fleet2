// pdf_print.js

document.addEventListener('DOMContentLoaded', function() {
    const printBtn = document.getElementById('printBtn');
    printBtn.addEventListener('click', function() {
      // Enable PDF capture mode
      document.body.classList.add('pdf-capture');
      // Wait a moment for images and map tiles to load
      setTimeout(function() {
        const page1 = document.getElementById('page1Content');
        const page2 = document.getElementById('page2Content');
        html2canvas(page1, { useCORS: true, scale: 2 }).then(canvas1 => {
          const { jsPDF } = window.jspdf;
          const pdf = new jsPDF('p', 'mm', 'a4');
          const pdfWidth = pdf.internal.pageSize.getWidth();
          const pdfHeight = pdf.internal.pageSize.getHeight();
          const imgData1 = canvas1.toDataURL('image/png');
          pdf.addImage(imgData1, 'PNG', 0, 0, pdfWidth, pdfHeight);
          pdf.addPage();
          html2canvas(page2, { useCORS: true, scale: 2 }).then(canvas2 => {
            const imgData2 = canvas2.toDataURL('image/png');
            pdf.addImage(imgData2, 'PNG', 0, 0, pdfWidth, pdfHeight);
            pdf.save("trip_details.pdf");
            document.body.classList.remove('pdf-capture');
          });
        });
      }, 600);
    });
  });
  