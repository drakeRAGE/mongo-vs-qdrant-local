#!/bin/bash
set -e

echo "Starting MongoDB initialization..."
sleep 2

mongosh --eval "
const adminDb = db.getSiblingDB('admin');
try {
  adminDb.createUser({
    user: 'admin',
    pwd: 'admin',
    roles: [ { role: 'root', db: 'admin' } ]
  });
  print('User admin created successfully');
} catch (error) {
  if (error.code === 11000) {
    print('User admin already exists');
  } else {
    print('Error creating admin: ' + error);
  }
}
try {
  adminDb.createUser({
    user: 'mongotUser',
    pwd: 'mongotPassword',
    roles: [{ role: 'searchCoordinator', db: 'admin' }]
  });
  print('User mongotUser created successfully');
} catch (error) {
  if (error.code === 11000) {
    print('User mongotUser already exists');
  } else {
    print('Error creating mongotUser: ' + error);
  }
}
"

echo "MongoDB initialization completed."
