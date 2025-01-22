const int analogPin = A0;             // Analog pin connected to the voltage divider
const int seriesResistor = 10000;     // 10kΩ resistor
const int thermistorNominal = 10000;  // Resistance at 25 degrees C (10kΩ)
const int tempNominal = 25;           // Nominal temperature (25 degrees C)
const int betaCoefficient = 3950;     // Beta coefficient of the thermistor
const int numSamples = 10;             // Reduced number of samples for averaging
const unsigned long interval = 500;   // Interval between readings in milliseconds

unsigned long previousMillis = 0;

void setup() {
  Serial.begin(115200); // Initialize serial communication
}

void loop() {
  unsigned long currentMillis = millis();
  
  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;
    
    uint16_t total = 0;

    // Read analog samples for averaging
    for (int i = 0; i < numSamples; i++) {
      total += analogRead(analogPin);
      delay(10); // Small delay between samples
    }

    // Calculate the average
    float average = total / numSamples;

    // Convert the analog value to resistance
    float voltage = average * (5.0 / 1023.0);
    float resistance = (5.0 - voltage) * seriesResistor / voltage;

    // Calculate temperature using the Beta equation
    float steinhart;
    steinhart = resistance / thermistorNominal;     // (R/Ro)
    steinhart = log(steinhart);                     // ln(R/Ro)
    steinhart /= betaCoefficient;                   // 1/B * ln(R/Ro)
    steinhart += 1.0 / (tempNominal + 273.15);      // + (1/To)
    steinhart = 1.0 / steinhart;                    // Invert
    steinhart -= 273.15;                            // Convert to Celsius

    // Send temperature data via Serial
    Serial.println(steinhart);
  }
}