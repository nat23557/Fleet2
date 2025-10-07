document.addEventListener('DOMContentLoaded', function() {
    var printBtn = document.getElementById('printBtn');
    printBtn.addEventListener('click', function() {
      // Activate print styles
      document.body.classList.add('pdf-capture');
      // Increase delay to ensure all images load
      setTimeout(function() {
        var page1 = document.getElementById('page1Content');
        html2canvas(page1, { useCORS: true, scale: 2 }).then(function(canvas1) {
          // Debug: Log the dataURL length
          console.log('Page 1 dataURL length:', canvas1.toDataURL().length);
          var { jsPDF } = window.jspdf;
          var pdf = new jsPDF('p', 'mm', 'a4');
          var pdfWidth = pdf.internal.pageSize.getWidth();
          var pdfHeight = pdf.internal.pageSize.getHeight();
          var imgData1 = canvas1.toDataURL('image/png');
          try {
            pdf.addImage(imgData1, 'PNG', 0, 0, pdfWidth, pdfHeight);
          } catch (e) {
            console.error("Error adding Page 1 image:", e);
            alert("Error adding Page 1 image: " + e.message);
            document.body.classList.remove('pdf-capture');
            return;
          }
          
          pdf.addPage();
          var page2 = document.getElementById('page2Content');
          html2canvas(page2, { useCORS: true, scale: 2 }).then(function(canvas2) {
            console.log('Page 2 dataURL length:', canvas2.toDataURL().length);
            var imgData2 = canvas2.toDataURL('image/png');
            try {
              pdf.addImage(imgData2, 'PNG', 0, 0, pdfWidth, pdfHeight);
            } catch (e) {
              console.error("Error adding Page 2 image:", e);
              alert("Error adding Page 2 image: " + e.message);
              document.body.classList.remove('pdf-capture');
              return;
            }
            pdf.save("trip_details.pdf");
            document.body.classList.remove('pdf-capture');
          });
        });
      }, 1000); // Increased timeout (1000ms)
    });
  });
  