import numpy as np
from scipy.linalg import cholesky

class QuantumInspiredUKF:
    def __init__(self, dt=1.0):
        """
        Initializes the Quantum-Inspired UKF.
        State vector: [x_position, y_position, x_velocity, y_velocity]
        """
        self.n = 4  # Dimensionality of the state
        
        # 1. Initial State and Uncertainty
        self.state = np.zeros(self.n)
        self.P = np.eye(self.n) * 100.0  # Initial Covariance (High uncertainty)

        # 2. Quantum Spread Parameters (Controls the Probability Cloud)
        self.alpha = 1e-3  # Quantum Spread (how far the superposition reaches)
        self.kappa = 0     # Secondary scaling parameter
        self.beta = 2.0    # Optimal for Gaussian-like prior distributions
        self.lambda_q = (self.alpha**2) * (self.n + self.kappa) - self.n

        # 3. Physics / Kinematics (State Transition Matrix)
        # Assumes constant velocity model over time step 'dt'
        self.F = np.array([
            [1, 0, dt,  0], 
            [0, 1,  0, dt], 
            [0, 0,  1,  0], 
            [0, 0,  0,  1]
        ])

        # 4. Noise Matrices
        # Q = Process Noise (Physical unpredictability of human walking)
        self.Q = np.eye(self.n) * 0.1 
        # R = Measurement Noise (Inherent jitter of the raw Wi-Fi signals)
        self.R = np.eye(2) * 2.0      

        # 5. Superposition Collapse Weights (Wm for mean, Wc for covariance)
        self.Wm = np.full(2 * self.n + 1, 1 / (2 * (self.n + self.lambda_q)))
        self.Wc = np.full(2 * self.n + 1, 1 / (2 * (self.n + self.lambda_q)))
        self.Wm[0] = self.lambda_q / (self.n + self.lambda_q)
        self.Wc[0] = self.lambda_q / (self.n + self.lambda_q) + (1 - self.alpha**2 + self.beta)

    def _generate_superposition(self, state, covariance):
        """Creates the 'Sigma Points' cloud representing positional probability."""
        points = np.zeros((2 * self.n + 1, self.n))
        points[0] = state
        try:
            # Matrix square root to define the boundaries of the probability cloud
            U = cholesky((self.n + self.lambda_q) * covariance)
            for i in range(self.n):
                points[i + 1] = state + U[i]
                points[self.n + i + 1] = state - U[i]
        except np.linalg.LinAlgError:
            # Fallback matrix if positive-definite status is temporarily lost
            for i in range(self.n):
                points[i + 1] = state
                points[self.n + i + 1] = state
        return points

    def update(self, measurement):
        """
        Takes the raw [x, y] from the Wi-Fi scan, pushes the probability cloud,
        and collapses it to return the smoothed [x, y] coordinate.
        """
        # ==========================================
        # PHASE 1: PREDICT (Push the cloud through time)
        # ==========================================
        sigmas = self._generate_superposition(self.state, self.P)
        sigmas_f = np.zeros_like(sigmas)
        
        # Apply physics transition to every point in the superposition
        for i in range(2 * self.n + 1):
            sigmas_f[i] = np.dot(self.F, sigmas[i])

        # Calculate predicted mean state
        x_pred = np.dot(self.Wm, sigmas_f)
        
        # Calculate predicted covariance
        P_pred = self.Q.copy()
        for i in range(2 * self.n + 1):
            y = sigmas_f[i] - x_pred
            P_pred += self.Wc[i] * np.outer(y, y)

        # ==========================================
        # PHASE 2: MEASURE & COLLAPSE
        # ==========================================
        # Remap the predicted cloud into measurement space (we only measure X and Y)
        sigmas_h = np.zeros((2 * self.n + 1, 2))
        for i in range(2 * self.n + 1):
            sigmas_h[i] = [sigmas_f[i][0], sigmas_f[i][1]]

        # Calculate predicted measurement
        z_pred = np.dot(self.Wm, sigmas_h)
        
        # Calculate measurement covariance
        S = self.R.copy()
        for i in range(2 * self.n + 1):
            y = sigmas_h[i] - z_pred
            S += self.Wc[i] * np.outer(y, y)

        # Calculate Cross-Covariance
        Pxz = np.zeros((self.n, 2))
        for i in range(2 * self.n + 1):
            Pxz += self.Wc[i] * np.outer(sigmas_f[i] - x_pred, sigmas_h[i] - z_pred)

        # Calculate KALMAN GAIN (The mathematical 'collapse' trigger)
        K = np.dot(Pxz, np.linalg.inv(S))
        Z = np.array([measurement[0], measurement[1]])
        
        # Final State Update
        self.state = x_pred + np.dot(K, (Z - z_pred))
        self.P = P_pred - np.dot(K, np.dot(S, K.T))

        # Return the collapsed, smoothed [X, Y] coordinate
        return [round(float(self.state[0]), 3), round(float(self.state[1]), 3)]


# --- QUICK TEST MODULE ---
if __name__ == "__main__":
    print("INITIALIZING QUANTUM-INSPIRED UKF...")
    tracker = QuantumInspiredUKF()
    
    # Simulating raw, jittery Wi-Fi inputs (e.g., walking in a straight line but signal bounces)
    raw_wifi_data = [
        [1.2, 0.9],
        [2.5, 1.1], # Big jitter jump
        [3.1, 0.8],
        [4.2, 1.0]
    ]
    
    print("\n[RAW WI-FI] -> [QI-UKF COLLAPSED STATE]")
    for raw in raw_wifi_data:
        smoothed = tracker.update(raw)
        print(f"Raw: {raw}  -->  Smoothed: {smoothed}")