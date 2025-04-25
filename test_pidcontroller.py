from controller_pid import PIDController
import time

# Example Usage (for testing purposes)
if __name__ == "__main__":
    # PID gains adjusted for slower reaction
    kp_init = 0.02
    ki_init = 0.001
    kd_init = 0.01 
    setpoint_init = 25.0

    pid = PIDController(kp=kp_init, ki=ki_init, kd=kd_init, setpoint=setpoint_init, 
                      output_min=35, output_max=75, ff_temp_coeff=1.1,
                      ff_wind_interaction_coeff=0.008,
                      valve_input_min=8.0, valve_input_max=70.0,
                      ff_sun_coeff=0.0001, time_factor=60) # Use the reduced value in example too

    # Simulate initial conditions
    wind = 4.0      
    outside_t = -14  
    sun = 15000      
    max_valve = 10     


    print(f"Initial PID: Kp={pid.kp}, Ki={pid.ki}, Kd={pid.kd}, Setpoint={pid.setpoint}")
    print(f"FF Coeffs: Temp={pid.ff_temp_coeff}, Wind={pid.ff_wind_coeff}, Sun={pid.ff_sun_coeff}, WindInteract={pid.ff_wind_interaction_coeff}") 
    print(f"Valve Input Scaling: [{pid.valve_input_min}, {pid.valve_input_max}] => [0, 100]") # Print scaling info
    print(f"Output Limits: [{pid.output_min}, {pid.output_max}]")
    print(f"Integral Limits (internal): [{pid._integral_min}, {pid._integral_max}]")
    print("--- Simulation Start ---")

    for i in range(225):
        boiler_temp = pid.update(max_valve, wind, outside_t, sun)
        print(f"Loop {i+1}: MaxValve={max_valve:.1f}%, Wind={wind}km/h, Temp={outside_t}C, Sun={sun}lux => Boiler Temp: {boiler_temp:.2f} C")
        
        # Simulate system response/change
        # max_valve -= 5.0 # Assume valve starts closing as temp increases
        max_valve += 0.1
        time.sleep(0.1) # Simulate 1 second interval

    # Simulate weather change
    print("--- Weather Change ---")
    wind = 15.0      
    outside_t = 17.0  
    sun = 1000.0      
    max_valve = 40.0 # Let's assume valve stabilized near setpoint before weather change

    for i in range(3):
        boiler_temp = pid.update(max_valve, wind, outside_t, sun)
        print(f"Loop {i+6}: MaxValve={max_valve:.1f}%, Wind={wind}km/h, Temp={outside_t}C, Sun={sun}lux => Boiler Temp: {boiler_temp:.2f} C")
        # Simulate slight valve increase due to colder weather needing more heat
        max_valve += 2.0 
        time.sleep(0.1)

    # Reset example
    print("--- Resetting PID ---")
    pid.reset()
    max_valve = 65.0 # Simulate high demand after reset
    boiler_temp = pid.update(max_valve, wind, outside_t, sun)
    print(f"Loop 9 (Post-Reset): MaxValve={max_valve:.1f}%, Wind={wind}km/h, Temp={outside_t}C, Sun={sun}lux => Boiler Temp: {boiler_temp:.2f} C")
