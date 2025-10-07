document.addEventListener("DOMContentLoaded", function() {
    var modal = document.getElementById("chartModal");
    var openLink = document.getElementById("openChartModal");
    var closeButton = document.getElementsByClassName("close-button")[0];
  
    openLink.addEventListener("click", function(e) {
      e.preventDefault(); // Prevent default link action
      modal.style.display = "block";
      // Here you can initialize/update the modal chart if needed.
    });
  
    closeButton.addEventListener("click", function() {
      modal.style.display = "none";
    });
  
    window.addEventListener("click", function(event) {
      if (event.target == modal) {
        modal.style.display = "none";
      }
    });
  });
  