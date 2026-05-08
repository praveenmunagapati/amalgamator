from greetings import greet, farewell
from math_utils import calculate_sum, calculate_average

def main():
    print(greet("World"))
    print(farewell("World"))

    numbers = [1, 2, 3, 4, 5]
    print(f"Sum: {calculate_sum(numbers)}")
    print(f"Average: {calculate_average(numbers)}")
    print("Amalgamator Python test works!")

if __name__ == "__main__":
    main()
