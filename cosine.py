import math

def dot(arr1, arr2):
    if len(arr1) != len(arr2):
        raise ValueError("Arrays must be of same size")
    return sum(arr1[i] * arr2[i] for i in range(len(arr1)))


def mod(arr):
    return math.sqrt(sum(x ** 2 for x in arr))


def cosine_similarity(a1, a2):
    denominator = mod(a1) * mod(a2)
    if denominator == 0:
        return 0.0
    return dot(a1, a2) / denominator