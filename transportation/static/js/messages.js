document.addEventListener("DOMContentLoaded", function () {
    const messages = document.querySelectorAll(".erp-message");
    
    if (messages.length > 0) {
        // Hide all but the last message
        messages.forEach((msg, index) => {
            if (index !== messages.length - 1) {
                msg.remove();
            }
        });

        // Show the last message
        const lastMessage = messages[messages.length - 1];
        lastMessage.style.display = "block";
        setTimeout(() => {
            lastMessage.style.opacity = "1";
            lastMessage.style.transform = "translateY(0)";
        }, 100);

        // Hide the message after 10 seconds
        setTimeout(() => {
            lastMessage.style.opacity = "0";
            lastMessage.style.transform = "translateY(-10px)";
            setTimeout(() => lastMessage.remove(), 5000);
        }, 10000);
    }
});
s