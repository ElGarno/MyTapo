# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the current directory contents into the container at /usr/src/app
COPY . .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir httpx asyncio python-dotenv tapo

# Make port 80 available to the world outside this container
# (Optional, only if your app uses a network port)
# EXPOSE 80

# Define environment variable
# (Optional, for example to turn on verbose logging in your application)
# ENV NAME World

# Run app.py when the container launches
CMD ["python", "./waching_machine_alert.py"]
