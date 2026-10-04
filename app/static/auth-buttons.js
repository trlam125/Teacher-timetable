(() => {
  'use strict';

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /* ==========================================================================
     1. LOGIN ANIMATION CONTROLLER
     ========================================================================== */
  const loginPoses = {
    hidden: {
      '--figure-duration': '180ms',
      '--figure-x': '-30px',
      '--figure-opacity': '0',
      '--figure-scale': '.92',
      '--arm1': 'rotate(-12deg)',
      '--wrist1': 'rotate(-8deg)',
      '--arm2': 'rotate(12deg)',
      '--wrist2': 'rotate(8deg)',
      '--leg1': 'rotate(-16deg)',
      '--calf1': 'rotate(14deg)',
      '--leg2': 'rotate(16deg)',
      '--calf2': 'rotate(-14deg)'
    },
    appear: {
      '--figure-duration': '220ms',
      '--figure-x': '-17px',
      '--figure-opacity': '1',
      '--figure-scale': '1',
      '--arm1': 'rotate(-42deg)',
      '--wrist1': 'rotate(-10deg)',
      '--arm2': 'rotate(38deg)',
      '--wrist2': 'rotate(8deg)',
      '--leg1': 'rotate(30deg)',
      '--calf1': 'rotate(-24deg)',
      '--leg2': 'rotate(-32deg)',
      '--calf2': 'rotate(20deg)'
    },
    step1: {
      '--figure-duration': '280ms',
      '--figure-x': '-7px',
      '--figure-opacity': '1',
      '--figure-scale': '.98',
      '--arm1': 'rotate(45deg)',
      '--wrist1': 'rotate(-4deg)',
      '--arm2': 'rotate(-48deg)',
      '--wrist2': 'rotate(5deg)',
      '--leg1': 'rotate(-34deg)',
      '--calf1': 'rotate(20deg)',
      '--leg2': 'rotate(34deg)',
      '--calf2': 'rotate(-18deg)'
    },
    step2: {
      '--figure-duration': '300ms',
      '--figure-x': '3px',
      '--figure-opacity': '1',
      '--figure-scale': '.92',
      '--arm1': 'rotate(-35deg)',
      '--wrist1': 'rotate(-8deg)',
      '--arm2': 'rotate(42deg)',
      '--wrist2': 'rotate(10deg)',
      '--leg1': 'rotate(26deg)',
      '--calf1': 'rotate(-20deg)',
      '--leg2': 'rotate(-28deg)',
      '--calf2': 'rotate(18deg)'
    },
    entering: {
      '--figure-duration': '320ms',
      '--figure-x': '14px',
      '--figure-opacity': '0',
      '--figure-scale': '.72',
      '--arm1': 'rotate(18deg)',
      '--wrist1': 'rotate(0deg)',
      '--arm2': 'rotate(-16deg)',
      '--wrist2': 'rotate(0deg)',
      '--leg1': 'rotate(-8deg)',
      '--calf1': 'rotate(4deg)',
      '--leg2': 'rotate(8deg)',
      '--calf2': 'rotate(-4deg)'
    }
  };

  function applyLoginPose(button, poseName) {
    const pose = loginPoses[poseName];
    if (!pose) return;
    Object.entries(pose).forEach(([prop, val]) => {
      button.style.setProperty(prop, val);
    });
  }

  function initLoginButtons() {
    const loginButtons = document.querySelectorAll('.loginButton');
    loginButtons.forEach((btn) => {
      applyLoginPose(btn, 'hidden');
      btn.dataset.running = 'false';
    });

    // Handle form submit with coordinated login animation
    const authForm = document.querySelector('form.auth-card');
    if (authForm) {
      const loginBtn = authForm.querySelector('.loginButton');
      if (loginBtn) {
        let isSubmitting = false;

        authForm.addEventListener('submit', async (e) => {
          if (isSubmitting) {
            e.preventDefault();
            return;
          }

          if (!authForm.checkValidity()) {
            return;
          }

          e.preventDefault();
          isSubmitting = true;
          loginBtn.dataset.running = 'true';
          loginBtn.classList.remove('login-error-shake');

          const btnText = loginBtn.querySelector('.button-text');
          const originalText = btnText ? btnText.textContent : 'Đăng nhập';
          if (btnText) btnText.textContent = 'Đang đăng nhập...';

          // Trigger server request in parallel
          const formData = new FormData(authForm);
          const requestPromise = fetch(authForm.action || '/login', {
            method: 'POST',
            body: new URLSearchParams(formData),
            headers: {
              'Content-Type': 'application/x-www-form-urlencoded',
              'X-Requested-With': 'XMLHttpRequest'
            },
            redirect: 'follow',
            credentials: 'same-origin'
          }).catch((err) => ({ networkError: true, error: err }));

          // 1) Door opens
          loginBtn.classList.add('running', 'opening');
          await sleep(190);

          // 2) Person appears outside the door
          applyLoginPose(loginBtn, 'appear');
          await sleep(230);

          // 3) Person walks toward the doorway
          applyLoginPose(loginBtn, 'step1');
          await sleep(285);
          applyLoginPose(loginBtn, 'step2');
          await sleep(300);

          // Check server response
          let response;
          try {
            response = await requestPromise;
          } catch (e) {
            response = { networkError: true };
          }

          if (response && response.ok && !response.networkError) {
            // 4) Person enters door and disappears inside
            applyLoginPose(loginBtn, 'entering');
            await sleep(255);

            // 5) Door closes
            loginBtn.classList.remove('opening');
            loginBtn.classList.add('closing');
            await sleep(240);

            // 6) Success mark pops up
            loginBtn.classList.add('success');
            if (btnText) btnText.textContent = 'Đã đăng nhập';
            await sleep(350);

            // Navigate to destination
            const redirectUrl = response.url || '/projects';
            window.location.href = redirectUrl;
          } else {
            // Failed login: door closes, person steps back
            applyLoginPose(loginBtn, 'hidden');
            loginBtn.classList.remove('opening');
            loginBtn.classList.add('closing');
            await sleep(200);

            // Shake button to indicate error
            loginBtn.classList.remove('running', 'closing');
            loginBtn.classList.add('login-error-shake');
            loginBtn.dataset.running = 'false';
            if (btnText) btnText.textContent = originalText;
            isSubmitting = false;

            // Extract error message from HTML response if available
            let errorMessage = 'Email hoặc mật khẩu không đúng';
            if (response && typeof response.text === 'function') {
              try {
                const text = await response.text();
                const parser = new DOMParser();
                const doc = parser.parseFromString(text, 'text/html');
                const errAlert = doc.querySelector('.alert.error, .alert');
                if (errAlert && errAlert.textContent.trim()) {
                  errorMessage = errAlert.textContent.trim();
                }
              } catch (err) {
                // Keep default message
              }
            }

            // Display alert banner
            let alertBox = authForm.querySelector('.alert.error');
            if (!alertBox) {
              alertBox = document.createElement('div');
              alertBox.className = 'alert error';
              const cardBody = authForm.querySelector('.auth-card-body');
              const firstLabel = cardBody ? cardBody.querySelector('label') : null;
              if (firstLabel) {
                cardBody.insertBefore(alertBox, firstLabel);
              } else if (cardBody) {
                cardBody.prepend(alertBox);
              }
            }
            if (alertBox) {
              alertBox.textContent = errorMessage;
              alertBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }

            // Focus password field for quick correction
            const passInput = authForm.querySelector('#authPassword');
            if (passInput) {
              passInput.focus();
              passInput.select();
            }

            setTimeout(() => {
              loginBtn.classList.remove('login-error-shake');
            }, 500);
          }
        });
      }
    }
  }


  /* ==========================================================================
     2. LOGOUT ANIMATION CONTROLLER
     ========================================================================== */
  const logoutButtonStates = {
    default: {
      '--figure-duration': '100',
      '--transform-figure': 'translateX(-24px) scale(0.92)',
      '--figure-opacity': '0',
      '--walking-duration': '100',
      '--transform-arm1': 'none',
      '--transform-wrist1': 'none',
      '--transform-arm2': 'none',
      '--transform-wrist2': 'none',
      '--transform-leg1': 'none',
      '--transform-calf1': 'none',
      '--transform-leg2': 'none',
      '--transform-calf2': 'none'
    },
    hover: {
      '--figure-duration': '100',
      '--transform-figure': 'translateX(-24px) scale(0.92)',
      '--figure-opacity': '0',
      '--walking-duration': '100',
      '--transform-arm1': 'none',
      '--transform-wrist1': 'none',
      '--transform-arm2': 'none',
      '--transform-wrist2': 'none',
      '--transform-leg1': 'none',
      '--transform-calf1': 'none',
      '--transform-leg2': 'none',
      '--transform-calf2': 'none'
    },
    emerge: {
      '--figure-duration': '220',
      '--transform-figure': 'translateX(-14px) scale(1)',
      '--figure-opacity': '1',
      '--walking-duration': '220',
      '--transform-arm1': 'rotate(-42deg)',
      '--transform-wrist1': 'rotate(-10deg)',
      '--transform-arm2': 'rotate(38deg)',
      '--transform-wrist2': 'rotate(8deg)',
      '--transform-leg1': 'rotate(30deg)',
      '--transform-calf1': 'rotate(-24deg)',
      '--transform-leg2': 'rotate(-32deg)',
      '--transform-calf2': 'rotate(20deg)'
    },
    step1: {
      '--figure-duration': '240',
      '--transform-figure': 'translateX(-5px) scale(0.98)',
      '--figure-opacity': '1',
      '--walking-duration': '240',
      '--transform-arm1': 'rotate(45deg)',
      '--transform-wrist1': 'rotate(-4deg)',
      '--transform-arm2': 'rotate(-48deg)',
      '--transform-wrist2': 'rotate(5deg)',
      '--transform-leg1': 'rotate(-34deg)',
      '--transform-calf1': 'rotate(20deg)',
      '--transform-leg2': 'rotate(34deg)',
      '--transform-calf2': 'rotate(-18deg)'
    },
    step2: {
      '--figure-duration': '220',
      '--transform-figure': 'translateX(3px) scale(0.96)',
      '--figure-opacity': '1',
      '--walking-duration': '220',
      '--transform-arm1': 'rotate(-35deg)',
      '--transform-wrist1': 'rotate(-8deg)',
      '--transform-arm2': 'rotate(42deg)',
      '--transform-wrist2': 'rotate(10deg)',
      '--transform-leg1': 'rotate(26deg)',
      '--transform-calf1': 'rotate(-20deg)',
      '--transform-leg2': 'rotate(-28deg)',
      '--transform-calf2': 'rotate(18deg)'
    },
    walking1: {
      '--figure-duration': '260',
      '--transform-figure': 'translateX(11px) scale(1)',
      '--figure-opacity': '1',
      '--walking-duration': '260',
      '--transform-arm1': 'translateX(-4px) translateY(-2px) rotate(120deg)',
      '--transform-wrist1': 'rotate(-5deg)',
      '--transform-arm2': 'translateX(4px) rotate(-110deg)',
      '--transform-wrist2': 'rotate(-5deg)',
      '--transform-leg1': 'translateX(-3px) rotate(80deg)',
      '--transform-calf1': 'rotate(-30deg)',
      '--transform-leg2': 'translateX(4px) rotate(-60deg)',
      '--transform-calf2': 'rotate(20deg)'
    },
    walking2: {
      '--figure-duration': '260',
      '--transform-figure': 'translateX(17px) scale(1)',
      '--figure-opacity': '1',
      '--walking-duration': '240',
      '--transform-arm1': 'rotate(60deg)',
      '--transform-wrist1': 'rotate(-15deg)',
      '--transform-arm2': 'rotate(-45deg)',
      '--transform-wrist2': 'rotate(6deg)',
      '--transform-leg1': 'rotate(-5deg)',
      '--transform-calf1': 'rotate(10deg)',
      '--transform-leg2': 'rotate(10deg)',
      '--transform-calf2': 'rotate(-20deg)'
    },
    falling1: {
      '--figure-duration': '1600',
      '--walking-duration': '400',
      '--transform-arm1': 'rotate(-60deg)',
      '--transform-wrist1': 'none',
      '--transform-arm2': 'rotate(30deg)',
      '--transform-wrist2': 'rotate(120deg)',
      '--transform-leg1': 'rotate(-30deg)',
      '--transform-calf1': 'rotate(-20deg)',
      '--transform-leg2': 'rotate(20deg)'
    },
    falling2: {
      '--walking-duration': '300',
      '--transform-arm1': 'rotate(-100deg)',
      '--transform-arm2': 'rotate(-60deg)',
      '--transform-wrist2': 'rotate(60deg)',
      '--transform-leg1': 'rotate(80deg)',
      '--transform-calf1': 'rotate(20deg)',
      '--transform-leg2': 'rotate(-60deg)'
    },
    falling3: {
      '--walking-duration': '300',
      '--transform-arm1': 'rotate(-30deg)',
      '--transform-wrist1': 'rotate(40deg)',
      '--transform-arm2': 'rotate(50deg)',
      '--transform-wrist2': 'none',
      '--transform-leg1': 'rotate(-30deg)',
      '--transform-leg2': 'rotate(20deg)',
      '--transform-calf2': 'none'
    }
  };

  function updateLogoutButtonState(button, state) {
    if (logoutButtonStates[state]) {
      button.state = state;
      for (const key in logoutButtonStates[state]) {
        button.style.setProperty(key, logoutButtonStates[state][key]);
      }
    }
  }

  async function triggerAnimatedLogout(button) {
    if (!button || button.dataset.loggingOut === 'true') return;
    button.dataset.loggingOut = 'true';
    button.style.pointerEvents = 'none';

    // 1) Door opens and figure begins emerging from the text
    button.classList.add('clicked');
    updateLogoutButtonState(button, 'emerge');
    await sleep(220);

    // 2) Person walks towards the door (step 1)
    updateLogoutButtonState(button, 'step1');
    await sleep(240);

    // 3) Person reaches the doorway (step 2)
    updateLogoutButtonState(button, 'step2');
    await sleep(220);

    // 4) Person walks through the doorway outside
    updateLogoutButtonState(button, 'walking1');
    await sleep(260);

    // 5) Door slams shut behind the person and person steps towards the edge
    button.classList.add('door-slammed');
    updateLogoutButtonState(button, 'walking2');
    await sleep(260);

    // 6) Person falls off the edge
    button.classList.add('falling');
    updateLogoutButtonState(button, 'falling1');
    await sleep(parseInt(logoutButtonStates['falling1']['--walking-duration'], 10) || 400);

    updateLogoutButtonState(button, 'falling2');
    await sleep(parseInt(logoutButtonStates['falling2']['--walking-duration'], 10) || 300);

    updateLogoutButtonState(button, 'falling3');
    await sleep(parseInt(logoutButtonStates['falling3']['--walking-duration'], 10) || 300);

    // 7) Redirect to logout route
    const logoutUrl = button.dataset.logoutUrl || '/logout';
    window.location.href = logoutUrl;
  }

  function initLogoutButtons() {
    document.querySelectorAll('.logoutButton').forEach((button) => {
      button.state = 'default';
      updateLogoutButtonState(button, 'default');

      button.addEventListener('mouseenter', () => {
        if (button.state === 'default' && button.dataset.loggingOut !== 'true') {
          updateLogoutButtonState(button, 'hover');
        }
      });

      button.addEventListener('mouseleave', () => {
        if (button.state === 'hover' && button.dataset.loggingOut !== 'true') {
          updateLogoutButtonState(button, 'default');
        }
      });

      button.addEventListener('click', (e) => {
        e.preventDefault();
        triggerAnimatedLogout(button);
      });
    });
  }

  // Export functions to global scope
  window.triggerAnimatedLogout = triggerAnimatedLogout;
  window.applyLoginPose = applyLoginPose;

  // Initialize once DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      initLoginButtons();
      initLogoutButtons();
    });
  } else {
    initLoginButtons();
    initLogoutButtons();
  }
})();
