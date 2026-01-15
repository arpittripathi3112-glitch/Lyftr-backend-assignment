# Lyftr Backend Assignment

This repository contains the backend service developed for the Lyftr assignment.
The project exposes basic health check APIs and is designed to run using Docker and Docker Compose.

## How to Run

1. Make sure Docker Desktop is installed and running.
2. Navigate to the project directory.
3. Run the following command:

   docker compose up --build

4. The service will start on port 8000.

## Health Check Endpoints

- http://localhost:8000/health/live
- http://localhost:8000/health/ready

## Author

Arpit Tripathi

## Setup Used

- VS Code  
- Docker & Docker Compose  
- Windows environment
