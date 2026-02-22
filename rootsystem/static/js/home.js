document.addEventListener('DOMContentLoaded', () => {
    console.log('Nori Framework: Home page loaded successfully.');

    // Example interaction to demonstrate JS inclusion
    const statusItems = document.querySelectorAll('.stat-item');
    statusItems.forEach(item => {
        item.addEventListener('mouseenter', () => {
            item.style.transform = 'translateY(-2px)';
            item.style.transition = 'transform 0.2s';
        });
        item.addEventListener('mouseleave', () => {
            item.style.transform = 'translateY(0)';
        });
    });
});
