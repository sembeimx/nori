document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.copy-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const cmd = btn.getAttribute('data-cmd');
            if (!cmd) return;

            const write = navigator.clipboard
                ? navigator.clipboard.writeText(cmd)
                : new Promise((resolve, reject) => {
                      const ta = document.createElement('textarea');
                      ta.value = cmd;
                      ta.style.position = 'fixed';
                      ta.style.opacity = '0';
                      document.body.appendChild(ta);
                      ta.select();
                      document.execCommand('copy') ? resolve() : reject();
                      document.body.removeChild(ta);
                  });

            write.then(() => {
                const original = btn.textContent;
                btn.textContent = 'Copied!';
                setTimeout(() => { btn.textContent = original; }, 1500);
            });
        });
    });
});
