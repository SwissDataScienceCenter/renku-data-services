"""Errors used by the notebook service.

The errors fall in three main groups. Each error has a specific code
whose value is based on the three broad error groups:
- User errors with codes ranging from 1000 to 1999
- Programming errors with codes ranging from 2000 to 2999
- Intermittent errors with codes ranging from: 3000 to 3999

The main difference between each of the three error groups is the following:
- User errors occur as a result of something the user did and the user can correct
based on the feedback received from the error. These errors should all be recoverable
without the involvement of a developer.
- Programming errors are bugs that the user cannot correct. They can only
be resolved by the developer and in most cases by deploying a new version of the notebook
service which corrects the specific error.
- Intermittent errors are the result of infrastructure problems that are outside of the
control of the user and developer. They can be resolved by a system administrator or by
simply retrying the action that caused the error in the first place.
"""
